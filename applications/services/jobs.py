"""Running OCR without holding the officer's request open.

OCR of a multi-page scan takes seconds, which is too long to block a web
request. It is not, however, worth standing up a broker and a worker fleet on
an on-premise server that processes a handful of applications a day, so work
runs in a background thread and progress is tracked in the database.

Because a thread dies with its process, `reclaim_stale()` and the
`process_ocr_queue` management command exist to recover anything a restart
interrupted.
"""
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from ..models import Application, ProcessingStatus
from .processing import DocumentProcessor

logger = logging.getLogger(__name__)


class AuditContext:
    """A safe stand-in for a request object inside a worker thread.

    Carries only the identity needed for the audit trail. The real request is
    tied to the response cycle and must not outlive it.
    """

    def __init__(self, user=None, ip=None):
        self.user = user
        self.META = {'REMOTE_ADDR': ip} if ip else {}

    @classmethod
    def from_request(cls, request):
        if request is None:
            return cls()
        from dashboard.audit import client_ip

        user = getattr(request, 'user', None)
        if user is not None and not user.is_authenticated:
            user = None
        return cls(user=user, ip=client_ip(request))


def queue_application(application, request=None):
    """Mark an application queued and start processing it."""
    application.processing_status = ProcessingStatus.QUEUED
    application.queued_at = timezone.now()
    application.error_message = ''
    application.save(
        update_fields=['processing_status', 'queued_at', 'error_message', 'updated_at']
    )

    context = AuditContext.from_request(request)

    if not getattr(settings, 'OCR_BACKGROUND', True):
        # Synchronous mode: used by the test suite and available to sites that
        # would rather have the request wait than manage a thread.
        run_now(application.pk, context)
        application.refresh_from_db()
        return application

    thread = threading.Thread(
        target=run_now,
        args=(application.pk, context),
        name=f'ocr-{application.reference}',
        daemon=False,
    )
    thread.start()
    return application


def run_now(application_id, context=None):
    """Process one application. Safe to call from a thread or a command."""
    try:
        application = Application.objects.get(pk=application_id)
    except Application.DoesNotExist:
        logger.warning('OCR job for unknown application %s', application_id)
        return

    try:
        DocumentProcessor().run(application, request=context)
    except Exception:
        # DocumentProcessor handles its own errors; this is the last resort so
        # an application can never be stranded in PROCESSING.
        logger.exception('OCR job crashed for application %s', application_id)
        try:
            application.refresh_from_db()
            if application.is_processing:
                application.processing_status = ProcessingStatus.FAILED
                application.error_message = (
                    'Processing stopped unexpectedly. Please try again.'
                )
                application.completed_at = timezone.now()
                application.save(
                    update_fields=[
                        'processing_status', 'error_message', 'completed_at',
                        'updated_at',
                    ]
                )
        except Exception:
            logger.exception('Could not mark application %s as failed', application_id)
    finally:
        # Threads get their own database connection; leaving it open leaks it.
        connection.close()


def reclaim_stale(timeout_seconds=None):
    """Fail applications whose processing was interrupted.

    A worker restart kills any in-flight thread, which would otherwise leave
    the application showing "OCR in progress" forever.
    """
    timeout_seconds = timeout_seconds or settings.OCR_TIMEOUT_SECONDS
    cutoff = timezone.now() - timedelta(seconds=timeout_seconds)

    stale = Application.objects.filter(
        processing_status__in=[ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING],
        updated_at__lt=cutoff,
    )
    count = 0
    for application in stale:
        application.processing_status = ProcessingStatus.FAILED
        application.error_message = (
            'Processing did not finish -- the server may have restarted while '
            'the documents were being read. Please try again.'
        )
        application.completed_at = timezone.now()
        application.save(
            update_fields=[
                'processing_status', 'error_message', 'completed_at', 'updated_at'
            ]
        )
        count += 1
    return count
