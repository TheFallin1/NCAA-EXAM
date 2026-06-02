import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ExamType(models.TextChoices):
    CABIN_CREW = 'cabin_crew', 'Cabin Crew'
    AME = 'ame', 'AME'
    PILOT = 'pilot', 'Pilot'
    FLIGHT_DISPATCH = 'flight_dispatch', 'Flight Dispatch'


class ExamSchedule(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate_name = models.CharField(max_length=255, db_index=True)
    exam_number = models.CharField(max_length=50, unique=True, db_index=True)
    receipt_number = models.CharField(max_length=50, db_index=True)
    company_name = models.CharField(max_length=255, db_index=True)
    exam_type = models.CharField(max_length=32, choices=ExamType.choices, db_index=True)
    exam_date = models.DateField(db_index=True)
    exam_time = models.TimeField()
    venue = models.CharField(max_length=255)
    photo = models.ImageField(upload_to='passports/%Y/%m/', blank=True, null=True)
    scheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='scheduled_exams',
    )
    slip_token = models.CharField(max_length=64, unique=True, editable=False, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-exam_date', '-exam_time']
        indexes = [
            models.Index(fields=['exam_date', 'exam_type']),
            models.Index(fields=['-created_at']),
        ]
        verbose_name = 'Exam Schedule'
        verbose_name_plural = 'Exam Schedules'

    def __str__(self):
        return f'{self.candidate_name} ({self.exam_number})'

    def save(self, *args, **kwargs):
        if not self.slip_token:
            self.slip_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.exam_date and self.exam_date < timezone.localdate():
            raise ValidationError({'exam_date': 'Exam date cannot be in the past.'})

    @property
    def exam_type_display(self):
        return self.get_exam_type_display()
