"""Orchestration for one application: OCR, extraction, validation.

This is the only place that decides an application's processing status. It
creates no examination records -- everything it produces lands in the staging
tables for the officer to verify first.
"""
import logging

from django.db import transaction
from django.utils import timezone

from dashboard.audit import log_activity
from dashboard.models import ActivityLog
from exams import exam_types
from exams.models import ExamSchedule

from ..models import DocumentKind, ExtractedCandidate, ProcessingStatus
from .extraction import ApplicationExtractor, ReceiptExtractor
from .ocr import OCRError, get_engine, read_document

logger = logging.getLogger(__name__)


class DocumentProcessor:
    def __init__(self, engine=None):
        self.engine = engine
        self.application_extractor = ApplicationExtractor()
        self.receipt_extractor = ReceiptExtractor()

    def run(self, application, request=None):
        """Process an application end to end and persist the outcome.

        Always leaves the application in a terminal-for-now status, never
        stuck in PROCESSING, even when something fails.
        """
        if not application.has_both_documents:
            # Should be unreachable: the view refuses to queue without both.
            self._block(
                application,
                ProcessingStatus.DRAFT,
                'Both the application letter and the payment receipt are '
                'required before processing can begin. Missing: '
                + ', '.join(application.missing_documents)
                + '.',
            )
            return application

        application.processing_status = ProcessingStatus.PROCESSING
        application.started_at = timezone.now()
        application.error_message = ''
        application.save(
            update_fields=['processing_status', 'started_at', 'error_message', 'updated_at']
        )

        try:
            engine = self.engine or get_engine()
            letter_result = self._read(application.letter, engine)
            receipt_result = self._read(application.receipt, engine)
        except OCRError as exc:
            logger.warning('OCR failed for application %s: %s', application.reference, exc)
            self._block(application, ProcessingStatus.FAILED, str(exc))
            log_activity(
                request,
                ActivityLog.Action.OCR_FAILED,
                application,
                description=f'{application.reference}: {exc}',
            )
            return application
        except Exception as exc:  # unexpected engine or filesystem problem
            logger.exception('Unexpected OCR error for application %s', application.reference)
            self._block(
                application,
                ProcessingStatus.FAILED,
                f'The documents could not be processed: {exc}',
            )
            log_activity(
                request,
                ActivityLog.Action.OCR_FAILED,
                application,
                description=f'{application.reference}: {exc}',
            )
            return application

        if letter_result.is_empty:
            self._block(
                application,
                ProcessingStatus.FAILED,
                'No text could be read from the application letter. The scan '
                'may be blank, upside down, or too low in quality -- please '
                'rescan it and try again.',
            )
            return application

        log_activity(
            request,
            ActivityLog.Action.OCR_COMPLETED,
            application,
            description=(
                f'{application.reference}: letter {letter_result.page_count} page(s), '
                f'receipt {receipt_result.page_count} page(s)'
            ),
            metadata={
                'engine': letter_result.engine,
                'letter_confidence': letter_result.mean_confidence,
                'receipt_confidence': receipt_result.mean_confidence,
                'letter_text_layer': letter_result.used_text_layer,
            },
        )

        # -- examination type: detect, then compare with the officer ------
        detection = self.application_extractor.extract_exam_type(letter_result)
        application.detected_exam_type = detection.exam_type or ''
        application.detected_exam_type_evidence = (detection.evidence or '')[:255]
        application.detected_exam_type_ambiguous = detection.ambiguous

        if not detection.detected:
            self._block(
                application,
                ProcessingStatus.MISMATCH,
                'The examination type could not be determined from the '
                'application letter, so it cannot be checked against your '
                'selection. Verify the letter and rescan it if necessary.',
                extra_fields=[
                    'detected_exam_type',
                    'detected_exam_type_evidence',
                    'detected_exam_type_ambiguous',
                ],
            )
            log_activity(
                request,
                ActivityLog.Action.EXAM_TYPE_MISMATCH,
                application,
                description=f'{application.reference}: no examination type detected',
                metadata={'officer_selected': application.exam_type, 'detected': None},
            )
            return application

        if not exam_types.matches(application.exam_type, detection.exam_type):
            self._block(
                application,
                ProcessingStatus.MISMATCH,
                '',
                extra_fields=[
                    'detected_exam_type',
                    'detected_exam_type_evidence',
                    'detected_exam_type_ambiguous',
                ],
            )
            log_activity(
                request,
                ActivityLog.Action.EXAM_TYPE_MISMATCH,
                application,
                description=(
                    f'{application.reference}: officer selected '
                    f'{application.exam_type_label}, letter states '
                    f'{application.detected_exam_type_label}'
                ),
                metadata={
                    'officer_selected': application.exam_type,
                    'detected': detection.exam_type,
                    'evidence': detection.evidence,
                },
            )
            return application

        # -- candidates ----------------------------------------------------
        candidates = self.application_extractor.extract_candidates(letter_result)
        if not candidates:
            self._block(
                application,
                ProcessingStatus.FAILED,
                'No candidate names could be read from the application letter. '
                'Check that the letter lists the candidates, and rescan it at a '
                'higher quality if the text is faint.',
                extra_fields=[
                    'detected_exam_type',
                    'detected_exam_type_evidence',
                    'detected_exam_type_ambiguous',
                ],
            )
            return application

        # -- receipt -------------------------------------------------------
        receipt_match = self.receipt_extractor.extract_receipt_number(receipt_result)
        application.receipt_number = receipt_match.value
        application.receipt_number_confidence = receipt_match.confidence

        if not application.company_name:
            application.company_name = self.application_extractor.extract_company(
                letter_result
            )[:255]

        with transaction.atomic():
            self._store_candidates(application, candidates)
            application.processing_status = ProcessingStatus.REVIEW
            application.completed_at = timezone.now()
            application.error_message = ''
            application.save()

        return application

    # -- helpers -----------------------------------------------------------
    def _read(self, document, engine):
        """OCR one document and persist the result onto it."""
        result = read_document(document.file.path, engine=engine, hint=document.kind)
        document.raw_text = result.text
        document.page_count = result.page_count
        document.mean_confidence = result.mean_confidence
        document.engine = result.engine
        document.duration_ms = result.duration_ms
        document.used_text_layer = result.used_text_layer
        document.rotation_applied = result.rotation
        document.skew_applied = result.skew or None
        document.save(
            update_fields=[
                'raw_text', 'page_count', 'mean_confidence', 'engine',
                'duration_ms', 'used_text_layer', 'rotation_applied',
                'skew_applied',
            ]
        )
        return result

    def _store_candidates(self, application, candidates):
        """Replace the staging rows, so a retry is idempotent."""
        application.extracted_candidates.all().delete()
        for position, match in enumerate(candidates, start=1):
            ExtractedCandidate.objects.create(
                application=application,
                position=position,
                raw_name=match.name[:255],
                confidence=match.confidence,
                needs_review=match.needs_review,
                possible_duplicate_of=self._find_duplicate(application, match.name),
            )

    def _find_duplicate(self, application, name):
        """An existing examination record for the same person and type."""
        return (
            ExamSchedule.objects.filter(
                candidate_name__iexact=name.strip(),
                exam_type=application.exam_type,
            )
            .order_by('-created_at')
            .first()
        )

    def _block(self, application, status, message, extra_fields=None):
        application.processing_status = status
        application.error_message = message
        application.completed_at = timezone.now()
        fields = [
            'processing_status', 'error_message', 'completed_at', 'updated_at'
        ]
        fields.extend(extra_fields or [])
        application.save(update_fields=fields)
