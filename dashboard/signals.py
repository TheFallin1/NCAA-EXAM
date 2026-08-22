from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from exams.models import ExamPaper, ExamSchedule

from .audit import log_activity
from .models import ActivityLog


def _describe(instance):
    return f'{instance.candidate_name} - {instance.exam_number}'


@receiver(post_save, sender=ExamSchedule)
def log_exam_save(sender, instance, created, **kwargs):
    request = getattr(instance, '_request', None)
    action = ActivityLog.Action.CREATE if created else ActivityLog.Action.UPDATE
    log_activity(
        request,
        action,
        instance,
        model_name='ExamSchedule',
        description=_describe(instance),
    )


@receiver(post_delete, sender=ExamSchedule)
def log_exam_delete(sender, instance, **kwargs):
    request = getattr(instance, '_request', None)
    log_activity(
        request,
        ActivityLog.Action.DELETE,
        instance,
        model_name='ExamSchedule',
        description=_describe(instance),
    )


@receiver(post_save, sender=ExamPaper)
def log_paper_save(sender, instance, created, **kwargs):
    """Record Paper 1 / Paper 2 scheduling separately from the parent record."""
    if not instance.exam_date:
        return
    request = getattr(instance, '_request', None)
    log_activity(
        request,
        ActivityLog.Action.PAPER_SCHEDULED,
        instance,
        model_name='ExamPaper',
        description=(
            f'{instance.exam.exam_number} - {instance.get_paper_display()} on '
            f'{instance.exam_date} at {instance.exam_time} ({instance.venue})'
        ),
    )
