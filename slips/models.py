from django.conf import settings
from django.db import models
from django.utils import timezone

from exams.models import ExamSchedule


class SlipRecord(models.Model):
    exam = models.OneToOneField(
        ExamSchedule,
        on_delete=models.CASCADE,
        related_name='slip_record',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='created_slip_records',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_viewed_at = models.DateTimeField(blank=True, null=True)
    pdf_generated_at = models.DateTimeField(blank=True, null=True)
    preview_count = models.PositiveIntegerField(default=0)
    pdf_download_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # Names pinned to those created by migration 0001. Django's
            # auto-generated hash drifted between point releases, and
            # renaming indexes on the live table buys nothing.
            models.Index(fields=['-created_at'], name='slips_slipr_created_8a9b15_idx'),
            models.Index(fields=['pdf_generated_at'], name='slips_slipr_pdf_gen_7a6c42_idx'),
        ]
        verbose_name = 'Slip Record'
        verbose_name_plural = 'Slip Records'

    def __str__(self):
        return f'Slip for {self.exam.exam_number}'

    @classmethod
    def record_preview(cls, exam, user):
        record, _ = cls.objects.get_or_create(
            exam=exam,
            defaults={'created_by': user if user.is_authenticated else None},
        )
        record.preview_count = models.F('preview_count') + 1
        record.last_viewed_at = timezone.now()
        record.save(update_fields=['preview_count', 'last_viewed_at'])
        record.refresh_from_db(fields=['preview_count', 'last_viewed_at'])
        return record

    @classmethod
    def record_pdf_download(cls, exam, user):
        record, _ = cls.objects.get_or_create(
            exam=exam,
            defaults={'created_by': user if user.is_authenticated else None},
        )
        record.pdf_download_count = models.F('pdf_download_count') + 1
        record.pdf_generated_at = timezone.now()
        record.save(update_fields=['pdf_download_count', 'pdf_generated_at'])
        record.refresh_from_db(fields=['pdf_download_count', 'pdf_generated_at'])
        return record
