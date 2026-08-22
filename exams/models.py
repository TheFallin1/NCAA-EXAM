import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone


class ExamType(models.TextChoices):
    CABIN_CREW = 'cabin_crew', 'Cabin Crew'
    AME = 'ame', 'AME'
    PILOT = 'pilot', 'Pilot'
    FLIGHT_DISPATCH = 'flight_dispatch', 'Flight Dispatch'


class Paper(models.TextChoices):
    """Papers within an examination. Only Flight Dispatch uses these."""

    PAPER_1 = 'paper_1', 'Paper 1'
    PAPER_2 = 'paper_2', 'Paper 2'


class NumberSequence(models.Model):
    """Server-side counter behind examination IDs and application references.

    Kept in the database and incremented under a row lock so two officers
    confirming applications at the same moment cannot be handed the same
    number. Identifiers are never generated in the browser.
    """

    scope = models.CharField(max_length=32)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['scope', 'year'], name='unique_sequence_scope_year'
            )
        ]
        verbose_name = 'Number Sequence'
        verbose_name_plural = 'Number Sequences'

    def __str__(self):
        return f'{self.scope}/{self.year} = {self.last_value}'

    @classmethod
    def next_value(cls, scope, year):
        try:
            cls.objects.get_or_create(scope=scope, year=year)
        except IntegrityError:
            # Another worker created the row first; it exists either way.
            pass
        with transaction.atomic():
            row = cls.objects.select_for_update().get(scope=scope, year=year)
            row.last_value += 1
            row.save(update_fields=['last_value'])
            return row.last_value


class ExamSchedule(models.Model):
    """One candidate's examination record.

    For Flight Dispatch the per-paper schedule lives in the related ExamPaper
    rows; the date/time/venue held here mirror Paper 1 so that the dashboard,
    calendar, record list and CSV export continue to work unchanged.
    """

    class Status(models.TextChoices):
        PENDING_SCHEDULE = 'pending_schedule', 'Awaiting scheduling'
        SCHEDULED = 'scheduled', 'Scheduled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate_name = models.CharField(max_length=255, db_index=True)
    exam_number = models.CharField(max_length=50, unique=True, db_index=True)
    receipt_number = models.CharField(max_length=50, db_index=True)
    company_name = models.CharField(max_length=255, db_index=True)
    exam_type = models.CharField(max_length=32, choices=ExamType.choices, db_index=True)

    # Null between confirmation (when the examination ID is issued) and
    # scheduling. Populated for every scheduled examination.
    exam_date = models.DateField(db_index=True, null=True, blank=True)
    exam_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=255, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
        db_index=True,
    )
    photo = models.ImageField(upload_to='passports/%Y/%m/', blank=True, null=True)
    application = models.ForeignKey(
        'applications.Application',
        on_delete=models.PROTECT,
        related_name='exam_records',
        null=True,
        blank=True,
    )
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
            models.Index(fields=['status']),
        ]
        verbose_name = 'Exam Schedule'
        verbose_name_plural = 'Exam Schedules'

    def __str__(self):
        return f'{self.candidate_name} ({self.exam_number})'

    def save(self, *args, **kwargs):
        if not self.slip_token:
            self.slip_token = secrets.token_urlsafe(32)
        self.status = (
            self.Status.SCHEDULED if self.exam_date else self.Status.PENDING_SCHEDULE
        )
        # Keep the derived status persistent even on targeted field updates.
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            update_fields = set(update_fields)
            if 'exam_date' in update_fields:
                update_fields.add('status')
                kwargs['update_fields'] = update_fields
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        # Only guard new records. Existing records must stay editable so an
        # officer can correct a venue or spelling after the examination date.
        if self._state.adding and self.exam_date and self.exam_date < timezone.localdate():
            raise ValidationError({'exam_date': 'Exam date cannot be in the past.'})

    @property
    def exam_type_display(self):
        return self.get_exam_type_display()

    @property
    def has_papers(self):
        from .exam_types import has_papers

        return has_papers(self.exam_type)

    @property
    def is_scheduled(self):
        return self.status == self.Status.SCHEDULED

    def ordered_papers(self):
        """Papers in sitting order; empty for single-sitting examinations."""
        return list(self.papers.all())


class ExamPaper(models.Model):
    """The schedule for one paper of a multi-paper examination.

    Each paper carries its own date, time and venue so Flight Dispatch Paper 1
    and Paper 2 can sit on different days. When NCAA runs both papers in a
    single sitting the same values are simply stored on both rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    exam = models.ForeignKey(
        ExamSchedule, on_delete=models.CASCADE, related_name='papers'
    )
    paper = models.CharField(max_length=16, choices=Paper.choices)
    exam_date = models.DateField(null=True, blank=True)
    exam_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['paper']
        constraints = [
            models.UniqueConstraint(fields=['exam', 'paper'], name='unique_paper_per_exam')
        ]
        indexes = [models.Index(fields=['exam_date'])]
        verbose_name = 'Examination Paper'
        verbose_name_plural = 'Examination Papers'

    def __str__(self):
        return f'{self.exam.exam_number} — {self.get_paper_display()}'

    @property
    def is_scheduled(self):
        return self.exam_date is not None
