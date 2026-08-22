"""Central audit-trail helper.

Every officer action that changes an application, a candidate or a schedule is
recorded here. Logging must never take down the workflow it is recording, so
failures are swallowed and reported to the application log instead.
"""
import logging

logger = logging.getLogger(__name__)


def client_ip(request):
    if not request:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_activity(
    request,
    action,
    obj=None,
    model_name=None,
    description='',
    metadata=None,
    user=None,
):
    """Record one audited event.

    `metadata` carries before/after values for corrections. Keep it to the
    fields that were actually changed -- it is not a place for document
    contents or anything else sensitive.
    """
    from .models import ActivityLog

    try:
        if user is None and request is not None:
            candidate = getattr(request, 'user', None)
            if candidate is not None and candidate.is_authenticated:
                user = candidate

        if model_name is None and obj is not None:
            model_name = obj.__class__.__name__

        ActivityLog.objects.create(
            user=user,
            action=action,
            model_name=model_name or '',
            object_id=str(obj.pk) if obj is not None and obj.pk else '',
            description=description or (str(obj) if obj is not None else ''),
            ip_address=client_ip(request),
            metadata=metadata or None,
        )
    except Exception:
        logger.exception('Failed to write activity log entry for action=%s', action)
