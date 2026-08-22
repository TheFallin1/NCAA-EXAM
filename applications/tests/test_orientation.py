"""Page orientation and skew correction, against genuine recognition.

A scan handed in sideways used to read as noise: 25% confidence, no
examination type, invented candidate names. These tests render a letter, turn
it, and check the pipeline puts it back the right way up and reads it.

Skipped where Tesseract is not installed, so the rest of the suite still runs.
"""
import io
import unittest
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from applications.models import Application, ProcessingStatus
from applications.services.extraction import ApplicationExtractor
from applications.services.ocr import get_engine, read_document
from applications.services.preprocess import upscale
from exams.models import ExamType

from .base import CABIN_CREW_ABINITIO_LETTER, RECEIPT_TEXT, WorkflowTestCase
from .test_real_ocr import SKIP_REASON, rasterise, tesseract_available
from .test_workflow import ReviewHelperMixin

#: The application supplied by NCAA. Real candidate data, so it is kept out of
#: version control; the test runs when the file is present.
REAL_APPLICATION = Path('demo_documents/real/application.jpg')


def turn(png_bytes, degrees):
    """Rotate a PNG clockwise, as a page fed in the wrong way round."""
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes))
    if degrees:
        image = image.rotate(-degrees, expand=True)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class RotationRecoveryTests(WorkflowTestCase):
    """Every quarter turn must be detected and undone."""

    def read_turned(self, degrees):
        path = f'{self._media_root}/turned{degrees}.png'
        with open(path, 'wb') as handle:
            handle.write(turn(rasterise(CABIN_CREW_ABINITIO_LETTER, dpi=200), degrees))
        return read_document(path, engine=get_engine(), hint='letter')

    def test_every_quarter_turn_still_reads(self):
        """What matters is that the page reads, not how it got there.

        Tesseract handles some orientations unaided, so the pipeline only
        turns a page when doing so is a clear improvement. Asserting a
        particular rotation would be testing the implementation; asserting the
        text comes out right is testing the guarantee.
        """
        extractor = ApplicationExtractor()
        for degrees in (0, 90, 180, 270):
            with self.subTest(degrees=degrees):
                result = self.read_turned(degrees)
                self.assertIn('CABIN CREW', result.text.upper())
                self.assertEqual(
                    extractor.extract_exam_type(result).exam_type,
                    ExamType.CABIN_CREW,
                )

    def test_an_upside_down_page_is_turned_back(self):
        """180 degrees is the case Tesseract cannot read on its own."""
        result = self.read_turned(180)
        self.assertEqual(result.rotation, 180)

    def test_a_sideways_page_still_reads(self):
        result = self.read_turned(90)
        self.assertGreater(result.mean_confidence, 70)
        self.assertIn('CABIN CREW', result.text.upper())

    def test_the_examination_type_survives_a_sideways_scan(self):
        extractor = ApplicationExtractor()
        for degrees in (90, 180, 270):
            with self.subTest(degrees=degrees):
                result = self.read_turned(degrees)
                detection = extractor.extract_exam_type(result)
                self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)
                self.assertTrue(detection.contextual)

    def test_candidates_survive_a_sideways_scan(self):
        result = self.read_turned(270)
        names = [c.name for c in ApplicationExtractor().extract_candidates(result)]
        self.assertEqual(names, ['ADAEZE FRANCA OKONKWO', 'JOSEPH JUDE KELECHI'])

    def test_an_upright_page_is_left_alone(self):
        self.assertEqual(self.read_turned(0).rotation, 0)

    @override_settings(OCR_AUTO_ROTATE=False)
    def test_correction_can_be_switched_off(self):
        result = self.read_turned(180)
        self.assertEqual(result.rotation, 0)
        # Without the correction an upside-down page is unreadable, which is
        # exactly what the correction exists to prevent.
        self.assertNotIn('CABIN CREW', result.text.upper())


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class SkewTests(WorkflowTestCase):
    def test_a_tilted_page_is_straightened(self):
        from PIL import Image

        page = Image.open(io.BytesIO(rasterise(CABIN_CREW_ABINITIO_LETTER, dpi=200)))
        tilted = page.rotate(-3, expand=True, fillcolor='white')
        path = f'{self._media_root}/tilted.png'
        tilted.save(path)

        result = read_document(path, engine=get_engine(), hint='letter')
        # The page leaned 3 degrees; the correction should lean back.
        self.assertGreater(result.skew, 1.0)
        self.assertIn('CABIN CREW', result.text.upper())


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class UpscaleTests(WorkflowTestCase):
    def test_a_small_page_is_enlarged(self):
        from PIL import Image

        small = Image.new('RGB', (600, 400), 'white')
        enlarged, factor = upscale(small)
        self.assertGreater(factor, 1.0)
        self.assertGreaterEqual(max(enlarged.size), settings.OCR_MIN_LONG_EDGE * 0.99)

    def test_a_large_page_is_left_alone(self):
        from PIL import Image

        large = Image.new('RGB', (4000, 3000), 'white')
        unchanged, factor = upscale(large)
        self.assertEqual(factor, 1.0)
        self.assertEqual(unchanged.size, (4000, 3000))


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@unittest.skipUnless(
    REAL_APPLICATION.exists(),
    f'The supplied NCAA application is not present at {REAL_APPLICATION}.',
)
@override_settings(OCR_ENGINE='tesseract')
class SuppliedApplicationTests(WorkflowTestCase):
    """Regression test against the application NCAA actually supplied.

    Sideways, photographed at low resolution, and carrying a Boeing 737 type
    rating exam in the body that must not be mistaken for the subject.
    """

    def read(self):
        return read_document(
            str(REAL_APPLICATION), engine=get_engine(), hint='letter'
        )

    def test_orientation_is_corrected(self):
        result = self.read()
        self.assertEqual(result.rotation, 90)
        self.assertGreater(result.mean_confidence, 70)

    def test_the_examination_type_is_cabin_crew(self):
        detection = ApplicationExtractor().extract_exam_type(self.read())
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)
        self.assertEqual(detection.label, 'Cabin Crew')
        self.assertTrue(detection.contextual)
        self.assertFalse(detection.ambiguous)

    def test_the_type_rating_in_the_body_is_not_the_subject(self):
        result = self.read()
        self.assertIn('737', result.text)
        detection = ApplicationExtractor().extract_exam_type(result)
        self.assertNotIn(ExamType.PILOT, detection.scores)
        self.assertNotIn(ExamType.AME, detection.scores)

    def test_both_candidates_are_read(self):
        names = [c.name for c in ApplicationExtractor().extract_candidates(self.read())]
        self.assertEqual(len(names), 2)
        self.assertIn('IWUORISHA FRANCA CHIEOFUNA', names)
        self.assertIn('JOSEPH JUDITH KELECHI', names)

    def test_the_applicant_not_the_recipient_is_recorded(self):
        company = ApplicationExtractor().extract_company(self.read())
        self.assertIn('AEROPORT', company.upper())
        self.assertNotIn('DIRECTOR GENERAL', company.upper())


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class SidewaysWorkflowTests(ReviewHelperMixin, WorkflowTestCase):
    """An officer uploading a sideways scan should not notice anything."""

    def test_a_sideways_application_processes_normally(self):
        self.client.post('/applications/process/', {
            'exam_type': 'cabin_crew',
            'application_letter': SimpleUploadedFile(
                'letter.png',
                turn(rasterise(CABIN_CREW_ABINITIO_LETTER, dpi=200), 90),
                content_type='image/png',
            ),
            'receipt': SimpleUploadedFile(
                'receipt.png', rasterise(RECEIPT_TEXT), content_type='image/png'
            ),
        })

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(application.detected_exam_type, ExamType.CABIN_CREW)
        self.assertEqual(application.extracted_candidates.count(), 2)

    def test_a_sideways_mismatch_is_still_caught(self):
        """Correcting the page must not weaken the match rule."""
        self.client.post('/applications/process/', {
            'exam_type': 'pilot',
            'application_letter': SimpleUploadedFile(
                'letter.png',
                turn(rasterise(CABIN_CREW_ABINITIO_LETTER, dpi=200), 270),
                content_type='image/png',
            ),
            'receipt': SimpleUploadedFile(
                'receipt.png', rasterise(RECEIPT_TEXT), content_type='image/png'
            ),
        })

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.MISMATCH)
        self.assertEqual(application.detected_exam_type, ExamType.CABIN_CREW)


REAL_RECEIPT = Path('demo_documents/real/receipt.jpg')


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@unittest.skipUnless(
    REAL_RECEIPT.exists(),
    f'The supplied NCAA receipt is not present at {REAL_RECEIPT}.',
)
@override_settings(OCR_ENGINE='tesseract')
class SuppliedReceiptTests(WorkflowTestCase):
    """Regression test against the receipt NCAA actually supplied.

    Photographed on a desk, largely handwritten, and carrying an invoice
    number, a date, a period and an amount alongside the receipt number.
    """

    #: The number printed against "Official Receipt ... No:".
    EXPECTED = '0125002'

    def read(self, degrees=0):
        from PIL import Image

        if not degrees:
            return read_document(
                str(REAL_RECEIPT), engine=get_engine(), hint='receipt'
            )
        path = f'{self._media_root}/receipt{degrees}.png'
        Image.open(REAL_RECEIPT).rotate(-degrees, expand=True).save(path)
        return read_document(path, engine=get_engine(), hint='receipt')

    def test_the_official_receipt_number_is_read(self):
        from applications.services.extraction import ReceiptExtractor

        match = ReceiptExtractor().extract_receipt_number(self.read())
        self.assertEqual(match.value, self.EXPECTED)

    def test_it_is_read_whichever_way_up_the_photograph_is(self):
        """Officers photograph receipts at any angle."""
        from applications.services.extraction import ReceiptExtractor

        extractor = ReceiptExtractor()
        for degrees in (0, 90, 180, 270):
            with self.subTest(degrees=degrees):
                match = extractor.extract_receipt_number(self.read(degrees))
                self.assertEqual(match.value, self.EXPECTED)

    def test_the_invoice_number_is_not_mistaken_for_it(self):
        from applications.services.extraction import ReceiptExtractor

        match = ReceiptExtractor().extract_receipt_number(self.read())
        self.assertNotIn('51003', match.value)

    def test_the_page_is_cropped_out_of_the_photograph(self):
        """The dark desk around the receipt has to go, or the small print
        is never read at all."""
        result = self.read()
        self.assertTrue(result.words)
        self.assertIsNotNone(result.page)


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class ContaminatedPageTests(WorkflowTestCase):
    """Photographs rarely contain only the page being processed.

    A second sheet, a stamp or marginalia at another angle drags the measured
    skew away from the body text. Applying that correction tilts a page that
    was already straight, and page segmentation then reads the intruder
    instead of the letter.
    """

    def build(self, degrees=90):
        """The letter with a strip of another page laid sideways across it."""
        from PIL import Image

        from .base import CABIN_CREW_ABINITIO_LETTER, COMMA_DELIMITED_LETTER

        body = Image.open(io.BytesIO(rasterise(COMMA_DELIMITED_LETTER, dpi=150)))
        other = Image.open(io.BytesIO(rasterise(CABIN_CREW_ABINITIO_LETTER, dpi=150)))
        strip = other.crop((0, 0, other.width, int(other.height * 0.35)))
        strip = strip.rotate(-degrees, expand=True)
        strip = strip.resize((body.width, int(body.height * 0.10)))

        page = Image.new('RGB', (body.width, body.height + strip.height), 'white')
        page.paste(strip, (0, 0))
        page.paste(body, (0, strip.height))

        path = f'{self._media_root}/contaminated.png'
        page.save(path)
        return path

    def test_the_letter_is_read_not_the_intruding_sheet(self):
        result = read_document(self.build(), engine=get_engine(), hint='letter')
        self.assertIn('CABIN CREW', result.text.upper())

        detection = ApplicationExtractor().extract_exam_type(result)
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)

    def test_the_candidate_list_survives(self):
        result = read_document(self.build(), engine=get_engine(), hint='letter')
        names = [c.name for c in ApplicationExtractor().extract_candidates(result)]
        self.assertIn('ALSAYED RANDA BASSAM', names)
        self.assertIn('PHILLIPS MONIOLUWA RITA', names)

    def test_a_correction_that_reads_worse_is_discarded(self):
        """Preparation is monotonic: no step is kept unless it helps."""
        from applications.services.preprocess import _deskew, _improves

        from .base import COMMA_DELIMITED_LETTER

        from PIL import Image

        page = Image.open(io.BytesIO(rasterise(COMMA_DELIMITED_LETTER, dpi=150)))
        engine = get_engine()

        # A straight page tilted by a bogus angle must not look like an
        # improvement over the straight one.
        self.assertFalse(_improves(_deskew(page, 4.0), page, engine))


@unittest.skipUnless(tesseract_available(), SKIP_REASON)
@override_settings(OCR_ENGINE='tesseract')
class CommaDelimitedLetterTests(ReviewHelperMixin, WorkflowTestCase):
    """The second real submission, end to end through the workflow."""

    def submit(self, exam_type='cabin_crew', degrees=0):
        from .base import COMMA_DELIMITED_LETTER

        page = rasterise(COMMA_DELIMITED_LETTER, dpi=150)
        if degrees:
            page = turn(page, degrees)
        return self.client.post('/applications/process/', {
            'exam_type': exam_type,
            'application_letter': SimpleUploadedFile(
                'letter.png', page, content_type='image/png'
            ),
            'receipt': SimpleUploadedFile(
                'receipt.png', rasterise(RECEIPT_TEXT), content_type='image/png'
            ),
        })

    def test_all_four_candidates_are_extracted(self):
        self.submit()
        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(application.detected_exam_type, ExamType.CABIN_CREW)
        self.assertEqual(application.extracted_candidates.count(), 4)

    def test_the_applicant_academy_is_recorded(self):
        self.submit()
        application = Application.objects.get()
        self.assertIn('LAGOS AVIATION', application.company_name.upper())

    def test_it_works_sideways_too(self):
        self.submit(degrees=90)
        application = Application.objects.get()
        self.assertEqual(application.detected_exam_type, ExamType.CABIN_CREW)
        self.assertEqual(application.extracted_candidates.count(), 4)
