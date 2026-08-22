import uuid

from django.conf import settings
from django.db import models


class ActivityLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'create', 'Created'
        UPDATE = 'update', 'Updated'
        DELETE = 'delete', 'Deleted'
        LOGIN = 'login', 'Signed in'
        APPLICATION_STARTED = 'app_started', 'Application processing started'
        DOCUMENT_UPLOADED = 'doc_uploaded', 'Document uploaded'
        OCR_COMPLETED = 'ocr_done', 'OCR completed'
        OCR_FAILED = 'ocr_failed', 'OCR failed'
        OCR_EDITED = 'ocr_edited', 'OCR result corrected'
        EXAM_TYPE_MISMATCH = 'type_mismatch', 'Examination type mismatch'
        CONFIRMED = 'confirmed', 'Application confirmed'
        EXAM_ID_GENERATED = 'exam_id', 'Examination ID generated'
        SCHEDULED = 'scheduled', 'Examination scheduled'
        PAPER_SCHEDULED = 'paper_sched', 'Examination paper scheduled'
        SLIP_GENERATED = 'slip', 'Examination slip generated'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='activity_logs',
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    # Before/after values for corrections, kept small and non-sensitive.
    metadata = models.JSONField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'

    def __str__(self):
        return f'{self.get_action_display()} {self.model_name} at {self.timestamp}'
