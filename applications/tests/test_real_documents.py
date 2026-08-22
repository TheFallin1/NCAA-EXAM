"""End-to-end checks against genuine PDF files, with no fake engine.

These exercise the real reading path: a real PDF is parsed by pypdfium2, its
embedded text layer is detected, and the extractors run on the text that
actually came out of the file.

Tesseract itself is not required here. A PDF that carries a text layer -- what
a searchable scan or any digitally produced letter gives you -- is read
directly, which is both exact and much faster than recognition.
"""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from applications.models import Application, ProcessingStatus
from applications.services.ocr import get_engine, read_document

from .base import PILOT_LETTER, RECEIPT_TEXT, WorkflowTestCase
from .test_workflow import ReviewHelperMixin


def build_pdf(text):
    """A real, valid PDF carrying `text` as a selectable text layer."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setFont('Helvetica', 11)
    y = A4[1] - 60
    for line in text.splitlines():
        pdf.drawString(60, y, line)
        y -= 16
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@override_settings(OCR_ENGINE='tesseract')
class RealPdfReadingTests(WorkflowTestCase):
    """The reading layer, driven by real files rather than a stub."""

    def read(self, text, name='letter.pdf'):
        path = f'{self._media_root}/{name}'
        with open(path, 'wb') as handle:
            handle.write(build_pdf(text))
        return read_document(path, engine=get_engine(), hint='letter')

    def test_a_real_pdf_text_layer_is_read_without_recognition(self):
        result = self.read(PILOT_LETTER)
        self.assertTrue(result.used_text_layer)
        self.assertEqual(result.page_count, 1)
        self.assertFalse(result.is_empty)

    def test_the_text_of_a_real_pdf_survives_the_round_trip(self):
        result = self.read(PILOT_LETTER)
        for expected in (
            'APPLICATION FOR PILOT EXAMINATION',
            'JOHN ADEWALE',
            'PETER WILLIAMS',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, result.text)

    def test_candidates_extract_from_a_real_pdf(self):
        from applications.services.extraction import ApplicationExtractor

        result = self.read(PILOT_LETTER)
        names = [c.name for c in ApplicationExtractor().extract_candidates(result)]
        self.assertEqual(
            names,
            [
                'JOHN ADEWALE', 'DAVID OKORO', 'MICHAEL IBRAHIM',
                'PETER WILLIAMS', 'SAMUEL ADEYEMI',
            ],
        )

    def test_the_examination_type_extracts_from_a_real_pdf(self):
        from applications.services.extraction import ApplicationExtractor

        detection = ApplicationExtractor().extract_exam_type(self.read(PILOT_LETTER))
        self.assertEqual(detection.exam_type, 'pilot')

    def test_the_receipt_number_extracts_from_a_real_pdf(self):
        from applications.services.extraction import ReceiptExtractor

        result = self.read(RECEIPT_TEXT, name='receipt.pdf')
        match = ReceiptExtractor().extract_receipt_number(result)
        self.assertEqual(match.value, 'NCAA/2026/004821')

    def test_a_corrupt_pdf_is_reported_clearly(self):
        from applications.services.ocr import OCRError

        path = f'{self._media_root}/broken.pdf'
        with open(path, 'wb') as handle:
            handle.write(b'%PDF-1.4\nthis is not really a pdf')

        with self.assertRaises(OCRError) as ctx:
            read_document(path, engine=get_engine(), hint='letter')
        self.assertIn('rescan', str(ctx.exception).lower())


@override_settings(OCR_ENGINE='tesseract')
class RealDocumentWorkflowTests(ReviewHelperMixin, WorkflowTestCase):
    """Scenario A again, but driven by real PDF files."""

    def submit_real(self, exam_type='pilot', letter=PILOT_LETTER, receipt=RECEIPT_TEXT):
        return self.client.post('/applications/process/', {
            'exam_type': exam_type,
            'application_letter': SimpleUploadedFile(
                'letter.pdf', build_pdf(letter), content_type='application/pdf'
            ),
            'receipt': SimpleUploadedFile(
                'receipt.pdf', build_pdf(receipt), content_type='application/pdf'
            ),
        })

    def test_the_whole_workflow_runs_on_real_files(self):
        self.submit_real()
        application = Application.objects.get()

        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(application.detected_exam_type, 'pilot')
        self.assertEqual(application.receipt_number, 'NCAA/2026/004821')
        self.assertEqual(application.extracted_candidates.count(), 5)
        self.assertTrue(application.letter.used_text_layer)
        self.assertEqual(application.letter.page_count, 1)

        self.post_review(application)
        application.refresh_from_db()
        self.assertEqual(application.exam_records.count(), 5)

        self.client.post(
            f'/applications/{application.pk}/schedule/', self.schedule_data()
        )
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.SCHEDULED)

        response = self.client.get(f'/slips/application/{application.pk}/pdf/')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_a_mismatch_is_caught_on_real_files(self):
        from .base import CABIN_CREW_LETTER

        self.submit_real(exam_type='pilot', letter=CABIN_CREW_LETTER)
        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.MISMATCH)
        self.assertEqual(application.detected_exam_type, 'cabin_crew')

    def test_flight_dispatch_runs_on_real_files(self):
        from .base import FLIGHT_DISPATCH_LETTER

        self.submit_real(exam_type='flight_dispatch', letter=FLIGHT_DISPATCH_LETTER)
        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)

        self.post_review(application)
        self.client.post(
            f'/applications/{application.pk}/schedule/',
            self.schedule_data(multi_paper=True, shared=False),
        )

        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.SCHEDULED)
        for exam in application.exam_records.all():
            self.assertEqual(exam.papers.count(), 2)
