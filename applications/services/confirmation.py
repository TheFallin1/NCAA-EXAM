"""Turning a verified application into examination records.

Nothing in here runs until the officer has confirmed the extracted
information. This is the boundary between staging data and official records.
"""
from django.db import transaction
from django.utils import timezone

from dashboard.audit import log_activity
from dashboard.models import ActivityLog
from exams.models import PRIVATE_APPLICANT, ExamSchedule
from exams.services import generate_exam_number

from ..models import Application, ProcessingStatus


class ConfirmationError(Exception):
    """Raised when an application is not in a state that may be confirmed."""


def duplicate_receipt_match(application):
    """Another record already processed under this receipt number, or None.

    Covers both applications processed through this workflow and examination
    records created by hand under the older manual process.
    """
    receipt_number = (application.receipt_number or '').strip()
    if not receipt_number:
        return None

    duplicate = (
        Application.objects.filter(
            receipt_number__iexact=receipt_number,
            processing_status__in=[
                ProcessingStatus.CONFIRMED,
                ProcessingStatus.SCHEDULED,
            ],
        )
        .exclude(pk=application.pk)
        .first()
    )
    if duplicate is not None:
        return f'application {duplicate.reference}'

    legacy = (
        ExamSchedule.objects.filter(receipt_number__iexact=receipt_number)
        .exclude(application=application)
        .first()
    )
    if legacy is not None:
        return f'examination record {legacy.exam_number}'
    return None


def confirm(application, request=None, override_duplicate_receipt=False):
    """Create the examination records for a verified application.

    Issues one examination ID per included candidate, each carrying the
    application's examination category and paper type.
    """
    if application.processing_status != ProcessingStatus.REVIEW:
        raise ConfirmationError(
            'This application is not ready to be confirmed '
            f'(status: {application.get_processing_status_display()}).'
        )

    candidates = application.included_candidates
    if not candidates:
        raise ConfirmationError(
            'At least one candidate must be included before the application '
            'can be confirmed.'
        )

    missing_names = [c for c in candidates if not c.name.strip()]
    if missing_names:
        raise ConfirmationError('Every included candidate must have a name.')

    if not (application.receipt_number or '').strip():
        raise ConfirmationError(
            'The receipt number is required. Enter it from the payment receipt '
            'before confirming.'
        )

    duplicate = duplicate_receipt_match(application)
    if duplicate and not override_duplicate_receipt:
        raise ConfirmationError(
            f'Receipt number {application.receipt_number} has already been used '
            f'for {duplicate}. Confirm that this is not a duplicate submission '
            'before continuing.'
        )

    officer = getattr(request, 'user', None) or application.created_by
    if officer is not None and not getattr(officer, 'is_authenticated', True):
        officer = application.created_by

    created = []
    with transaction.atomic():
        for candidate in candidates:
            exam = ExamSchedule(
                candidate_name=candidate.name,
                exam_number=generate_exam_number(application.exam_category),
                receipt_number=application.receipt_number,
                # The officer may clear the box; an unnamed applicant is
                # still a private one, not a blank.
                company_name=application.company_name or PRIVATE_APPLICANT,
                exam_category=application.exam_category,
                paper_type=application.paper_type,
                exam_date=None,
                exam_time=None,
                venue='',
                application=application,
                scheduled_by=officer,
            )
            exam._request = request
            exam.save()
            created.append(exam)

            log_activity(
                request,
                ActivityLog.Action.EXAM_ID_GENERATED,
                exam,
                model_name='ExamSchedule',
                description=f'{exam.exam_number} issued to {exam.candidate_name}',
                metadata={
                    'application': application.reference,
                    'ocr_name': candidate.raw_name,
                    'confirmed_name': candidate.name,
                    'corrected': candidate.was_corrected,
                },
            )

        application.processing_status = ProcessingStatus.CONFIRMED
        application.confirmed_at = timezone.now()
        application.error_message = ''
        application.save(
            update_fields=[
                'processing_status', 'confirmed_at', 'error_message', 'updated_at'
            ]
        )

    log_activity(
        request,
        ActivityLog.Action.CONFIRMED,
        application,
        description=(
            f'{application.reference}: {len(created)} candidate(s) confirmed for '
            f'{application.exam_category_label} - {application.paper_type_label}'
        ),
        metadata={
            'receipt_number': application.receipt_number,
            'exam_category': application.exam_category,
            'paper_type': application.paper_type,
            'candidates': len(created),
            'duplicate_receipt_override': bool(duplicate and override_duplicate_receipt),
        },
    )
    return created


def apply_schedule(application, schedule, request=None):
    """Write one schedule onto every examination record in the application.

    An application covers one paper of one category, so there is a single
    date, time and venue: Flight Dispatch Paper 1 and Paper 2 are scheduled as
    the separate examinations they are, on their own applications.
    """
    if application.processing_status not in (
        ProcessingStatus.CONFIRMED,
        ProcessingStatus.SCHEDULED,
    ):
        raise ConfirmationError(
            'The application must be confirmed before it can be scheduled.'
        )

    exams = list(application.exam_records.all())
    if not exams:
        raise ConfirmationError('This application has no examination records.')

    with transaction.atomic():
        for exam in exams:
            exam.exam_date = schedule['exam_date']
            exam.exam_time = schedule['exam_time']
            exam.venue = schedule['venue']
            exam._request = request
            exam.save()

        application.processing_status = ProcessingStatus.SCHEDULED
        application.scheduled_at = timezone.now()
        application.save(
            update_fields=['processing_status', 'scheduled_at', 'updated_at']
        )

    log_activity(
        request,
        ActivityLog.Action.SCHEDULED,
        application,
        description=(
            f'{application.reference}: {len(exams)} examination(s) scheduled for '
            f'{application.exam_category_label} - {application.paper_type_label}'
        ),
        metadata={
            'candidates': len(exams),
            'exam_category': application.exam_category,
            'paper_type': application.paper_type,
        },
    )
    return exams
