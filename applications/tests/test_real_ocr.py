"""Genuine Tesseract recognition against rasterised page images.

Everything else in the suite either uses the fake engine or reads a PDF text
layer. These tests drive the real recognition path end to end: a page is
rendered to an image with no text layer -- what a flatbed scanner produces --
and Tesseract actually reads it.

Skipped automatically where Tesseract is not installed, so the rest of the
suite still runs on a machine without it.
"""
import io
import unittest

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from applications.models import Application, ProcessingStatus
from applications.services.ocr import get_engine, read_document

from .base import (
    CABIN_CREW_LETTER,
    FLIGHT_DISPATCH_LETTER,
    PILOT_LETTER,
    RECEIPT_TEXT,
    WorkflowTestCase,
)
from .test_real_documents import build_pdf
from .test_workflow import ReviewHelperMixin


def tesseract_available():
    try:
        return get_engine('tesseract').check_available()
    except Exception:
        return False


def rasterise(text, dpi=300):
    """Render text to a page image with no text layer, imitating a scan."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(io.BytesIO(build_pdf(text)))
    try:
        image = document[0].render(scale=dpi / 72.0).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()
    finally:
        document.close()


SKIP_REASON = 'Tesseract is not installed on this machine.'


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class TesseractRecognitionTests(WorkflowTestCase):
    def read_image(self, text, name='scan.png'):
        path = f'{self._media_root}/{name}'
        with open(path, 'wb') as handle:
            handle.write(rasterise(text))
        return read_document(path, engine=get_engine(), hint='letter')

    def test_a_scanned_page_is_recognised(self):
        result = self.read_image(PILOT_LETTER)
        self.assertFalse(result.used_text_layer)  # a real recognition run
        self.assertFalse(result.is_empty)
        self.assertEqual(result.page_count, 1)

    def test_recognition_reports_confidence(self):
        result = self.read_image(PILOT_LETTER)
        self.assertIsNotNone(result.mean_confidence)
        self.assertGreater(result.mean_confidence, 50)
        self.assertLessEqual(result.mean_confidence, 100)

    def test_candidate_names_survive_recognition(self):
        from applications.services.extraction import ApplicationExtractor

        result = self.read_image(PILOT_LETTER)
        names = [c.name for c in ApplicationExtractor().extract_candidates(result)]
        self.assertEqual(
            names,
            [
                'JOHN ADEWALE', 'DAVID OKORO', 'MICHAEL IBRAHIM',
                'PETER WILLIAMS', 'SAMUEL ADEYEMI',
            ],
        )

    def test_the_examination_type_survives_recognition(self):
        from applications.services.extraction import ApplicationExtractor

        extractor = ApplicationExtractor()
        for text, expected in (
            (PILOT_LETTER, 'pilot'),
            (CABIN_CREW_LETTER, 'cabin_crew'),
            (FLIGHT_DISPATCH_LETTER, 'flight_dispatch'),
        ):
            with self.subTest(expected=expected):
                detection = extractor.extract_exam_category(self.read_image(text))
                self.assertEqual(detection.exam_category, expected)

    def test_the_receipt_number_survives_recognition(self):
        from applications.services.extraction import ReceiptExtractor

        result = self.read_image(RECEIPT_TEXT, name='receipt.png')
        match = ReceiptExtractor().extract_receipt_number(result)
        self.assertEqual(match.value, 'NCAA/2026/004821')

    def test_a_scanned_pdf_is_recognised_too(self):
        """A PDF whose pages are images must be rasterised and read."""
        import pypdfium2 as pdfium
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        page_image = rasterise(PILOT_LETTER, dpi=200)
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.drawImage(
            ImageReader(io.BytesIO(page_image)), 0, 0,
            width=A4[0], height=A4[1],
        )
        pdf.showPage()
        pdf.save()

        path = f'{self._media_root}/scanned.pdf'
        with open(path, 'wb') as handle:
            handle.write(buffer.getvalue())

        result = read_document(path, engine=get_engine(), hint='letter')
        self.assertFalse(result.used_text_layer)
        self.assertIn('JOHN ADEWALE', result.text)


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class ScannedWorkflowTests(ReviewHelperMixin, WorkflowTestCase):
    """The officer's full journey, driven by scanned page images."""

    def submit_scan(self, exam_category='pilot', letter=PILOT_LETTER, receipt=RECEIPT_TEXT):
        return self.client.post('/applications/process/', {
            'exam_category': exam_category,
            'paper_type': self.default_paper(exam_category),
            'application_letter': SimpleUploadedFile(
                'letter.png', rasterise(letter), content_type='image/png'
            ),
            'receipt': SimpleUploadedFile(
                'receipt.png', rasterise(receipt), content_type='image/png'
            ),
        })

    def test_a_scanned_application_runs_end_to_end(self):
        self.submit_scan()
        application = Application.objects.get()

        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(application.detected_exam_category, 'pilot')
        self.assertEqual(application.receipt_number, 'NCAA/2026/004821')
        self.assertEqual(application.extracted_candidates.count(), 5)
        self.assertFalse(application.letter.used_text_layer)
        self.assertEqual(application.letter.engine, 'tesseract')
        self.assertIsNotNone(application.letter.mean_confidence)

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

    def test_a_mismatch_is_caught_on_a_scan(self):
        self.submit_scan(exam_category='pilot', letter=CABIN_CREW_LETTER)
        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.MISMATCH)
        self.assertEqual(application.detected_exam_category, 'cabin_crew')

    def test_flight_dispatch_runs_from_a_scan(self):
        self.submit_scan(
            exam_category='flight_dispatch', letter=FLIGHT_DISPATCH_LETTER
        )
        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)

        self.post_review(application)
        self.client.post(
            f'/applications/{application.pk}/schedule/', self.schedule_data()
        )
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.SCHEDULED)
        for exam in application.exam_records.all():
            self.assertEqual(exam.paper_type, 'paper_1')

    def test_a_blank_scan_is_reported_not_silently_accepted(self):
        self.client.post('/applications/process/', {
            'exam_category': 'pilot',
            'paper_type': 'general',
            'application_letter': SimpleUploadedFile(
                'blank.png', rasterise('\n\n\n'), content_type='image/png'
            ),
            'receipt': SimpleUploadedFile(
                'receipt.png', rasterise(RECEIPT_TEXT), content_type='image/png'
            ),
        })
        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.FAILED)
