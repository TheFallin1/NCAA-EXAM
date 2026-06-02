from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from exams.models import ExamSchedule

from .models import ActivityLog


def _client_ip(request):
    if not request:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _log(request, action, instance, description=''):
    ActivityLog.objects.create(
        user=request.user if request and request.user.is_authenticated else None,
        action=action,
        model_name='ExamSchedule',
        object_id=str(instance.pk) if instance.pk else '',
        description=description or str(instance),
        ip_address=_client_ip(request),
    )


@receiver(post_save, sender=ExamSchedule)
def log_exam_save(sender, instance, created, **kwargs):
    request = getattr(instance, '_request', None)
    action = ActivityLog.Action.CREATE if created else ActivityLog.Action.UPDATE
    desc = f'{instance.candidate_name} — {instance.exam_number}'
    _log(request, action, instance, desc)


@receiver(post_delete, sender=ExamSchedule)
def log_exam_delete(sender, instance, **kwargs):
    request = getattr(instance, '_request', None)
    desc = f'{instance.candidate_name} — {instance.exam_number}'
    _log(request, ActivityLog.Action.DELETE, instance, desc)
