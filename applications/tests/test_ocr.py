"""OCR service behaviour and failure handling."""
from datetime import timedelta

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from applications.models import Application, ProcessingStatus
from applications.services.jobs import reclaim_stale
from applications.services.ocr import (
    FakeEngine,
    OCRLine,
    OCRResult,
    OCRUnavailableError,
    TesseractEngine,
    get_engine,
)

from .base import WorkflowTestCase


class EngineSelectionTests(SimpleTestCase):
    @override_settings(OCR_ENGINE='tesseract')
    def test_tesseract_is_the_configured_default(self):
        self.assertIsInstance(get_engine(), TesseractEngine)

    @override_settings(OCR_ENGINE='fake')
    def test_fake_engine_is_selectable(self):
        self.assertIsInstance(get_engine(), FakeEngine)

    @override_settings(OCR_ENGINE='google-vision')
    def test_unknown_engine_is_refused(self):
        """Only self-hosted engines are configurable."""
        with self.assertRaises(OCRUnavailableError) as ctx:
            get_engine()
        self.assertIn('Unknown OCR engine', str(ctx.exception))


class OCRResultTests(SimpleTestCase):
    def test_text_joins_the_lines(self):
        result = OCRResult(lines=[OCRLine('one', 90), OCRLine('two', 80)])
        self.assertEqual(result.text, 'one\ntwo')

    def test_mean_confidence_averages_scored_lines(self):
        result = OCRResult(lines=[OCRLine('one', 90), OCRLine('two', 80)])
        self.assertEqual(result.mean_confidence, 85)

    def test_mean_confidence_ignores_unscored_lines(self):
        result = OCRResult(lines=[OCRLine('one', 90), OCRLine('two', None)])
        self.assertEqual(result.mean_confidence, 90)

    def test_mean_confidence_is_none_without_scores(self):
        self.assertIsNone(OCRResult(lines=[OCRLine('one', None)]).mean_confidence)

    def test_empty_result_is_detected(self):
        self.assertTrue(OCRResult(lines=[OCRLine('   ', 90)]).is_empty)


class OCRFailureTests(WorkflowTestCase):
    def test_engine_unavailable_marks_the_application_failed(self):
        FakeEngine.raise_error = OCRUnavailableError('Tesseract is not installed.')
        self.submit_application()

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.FAILED)
        self.assertIn('Tesseract is not installed', application.error_message)

    def test_a_failed_application_creates_no_examination_records(self):
        from exams.models import ExamSchedule

        FakeEngine.raise_error = OCRUnavailableError('engine down')
        self.submit_application()
        self.assertFalse(ExamSchedule.objects.exists())

    def test_unreadable_letter_asks_for_a_rescan(self):
        self.set_ocr_text(letter='', receipt=self.receipt_text)
        self.submit_application()

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.FAILED)
        self.assertIn('rescan', application.error_message.lower())

    def test_a_failed_application_can_be_retried(self):
        FakeEngine.raise_error = OCRUnavailableError('engine down')
        self.submit_application()
        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.FAILED)

        # The engine recovers and the officer retries.
        FakeEngine.raise_error = None
        response = self.client.post(f'/applications/{application.pk}/retry/')
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(application.extracted_candidates.count(), 5)

    def test_retry_replaces_previous_candidates(self):
        """A rescan must not stack a second set of names on the first."""
        self.submit_application()
        application = Application.objects.get()
        self.assertEqual(application.extracted_candidates.count(), 5)

        self.client.post(f'/applications/{application.pk}/retry/')
        application.refresh_from_db()
        self.assertEqual(application.extracted_candidates.count(), 5)

    def test_letter_without_names_blocks_processing(self):
        self.set_ocr_text(
            letter='APPLICATION FOR PILOT EXAMINATION\nWe write to enquire.',
            receipt=self.receipt_text,
        )
        self.submit_application()

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.FAILED)
        self.assertIn('No candidate names', application.error_message)


class StaleJobTests(WorkflowTestCase):
    def test_interrupted_processing_is_reclaimed(self):
        """A server restart must not strand an application in PROCESSING."""
        self.submit_application()
        application = Application.objects.get()

        Application.objects.filter(pk=application.pk).update(
            processing_status=ProcessingStatus.PROCESSING,
            updated_at=timezone.now() - timedelta(hours=2),
        )

        self.assertEqual(reclaim_stale(timeout_seconds=60), 1)
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.FAILED)
        self.assertIn('did not finish', application.error_message)

    def test_recent_processing_is_left_alone(self):
        self.submit_application()
        Application.objects.update(processing_status=ProcessingStatus.PROCESSING)
        self.assertEqual(reclaim_stale(timeout_seconds=3600), 0)
