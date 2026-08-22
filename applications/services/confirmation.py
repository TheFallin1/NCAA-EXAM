"""Turning a verified application into examination records.

Nothing in here runs until the officer has confirmed the extracted
information. This is the boundary between staging data and official records.
"""
from django.db import transaction
from django.utils import timezone

from dashboard.audit import log_activity
from dashboard.models import ActivityLog
from exams.exam_types import has_papers
from exams.models import ExamPaper, ExamSchedule, Paper
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

    Issues one examination ID per included candidate. For Flight Dispatch an
    unscheduled Paper 1 and Paper 2 row is created alongside each record, ready
    for the scheduling step.
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
                exam_number=generate_exam_number(application.exam_type),
                receipt_number=application.receipt_number,
                company_name=application.company_name,
                exam_type=application.exam_type,
                exam_date=None,
                exam_time=None,
                venue='',
                application=application,
                scheduled_by=officer,
            )
            exam._request = request
            exam.save()

            if has_papers(application.exam_type):
                for paper in (Paper.PAPER_1, Paper.PAPER_2):
                    ExamPaper.objects.create(exam=exam, paper=paper)

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
            f'{application.exam_type_label}'
        ),
        metadata={
            'receipt_number': application.receipt_number,
            'candidates': len(created),
            'duplicate_receipt_override': bool(duplicate and override_duplicate_receipt),
        },
    )
    return created


def apply_schedule(application, primary, paper_schedules=None, request=None):
    """Write the schedule onto every examination record in the application.

    `primary` is a dict of date/time/venue used for single-sitting
    examinations. `paper_schedules` maps a Paper value to the same shape and is
    used for Flight Dispatch, where Paper 1 and Paper 2 usually sit on
    different days.

    For multi-paper examinations the parent record mirrors Paper 1 so the
    dashboard, calendar and record list keep working from a single date field.
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

    multi_paper = has_papers(application.exam_type)

    with transaction.atomic():
        for exam in exams:
            if multi_paper:
                for paper in exam.papers.all():
                    values = (paper_schedules or {}).get(paper.paper)
                    if not values:
                        continue
                    paper.exam_date = values['exam_date']
                    paper.exam_time = values['exam_time']
                    paper.venue = values['venue']
                    paper._request = request
                    paper.save()

                first = exam.papers.filter(paper=Paper.PAPER_1).first()
                mirror = first or exam.papers.first()
                if mirror is not None:
                    exam.exam_date = mirror.exam_date
                    exam.exam_time = mirror.exam_time
                    exam.venue = mirror.venue
            else:
                exam.exam_date = primary['exam_date']
                exam.exam_time = primary['exam_time']
                exam.venue = primary['venue']

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
            f'{application.exam_type_label}'
        ),
        metadata={'candidates': len(exams), 'multi_paper': multi_paper},
    )
    return exams
