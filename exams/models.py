import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone


class ExamCategory(models.TextChoices):
    """The examination categories NCAA runs.

    The first of the two dependent selections an officer makes. Which papers
    sit under each category is not fixed here -- that is configuration, held in
    PaperType -- so a paper can be added or renamed without touching this.

    Declared in the order the dropdown offers them.
    """

    CABIN_CREW = 'cabin_crew', 'Cabin Crew'
    PILOT = 'pilot', 'Pilot'
    FLIGHT_DISPATCH = 'flight_dispatch', 'Flight Dispatch'
    AME = 'ame', 'AME'


class PaperType(models.Model):
    """One paper offered under one examination category.

    These rows *are* the configuration behind the Paper Type dropdown, the OCR
    paper detection and the validation of a category/paper pair. NCAA can add,
    rename or retire a paper from the admin without a code or schema change,
    which is what the placeholder AME papers need: their official names are not
    yet confirmed.

    `code` is the stable value written onto an examination record; `name` is
    the label officers read. Renaming a paper therefore relabels it everywhere
    without rewriting a single historical record.
    """

    exam_category = models.CharField(
        max_length=32, choices=ExamCategory.choices, db_index=True
    )
    code = models.SlugField(
        max_length=32,
        help_text=(
            'Stable identifier stored on examination records. Do not change it '
            'once records exist -- change the name instead.'
        ),
    )
    name = models.CharField(
        max_length=100,
        help_text='The label officers see, e.g. "B737" or "General Paper".',
    )
    detection_terms = models.TextField(
        blank=True,
        help_text=(
            'One phrase per line that names this paper in an application '
            'letter, e.g. "B737". A phrase only counts where it appears in an '
            'examination context, so the same words in a letterhead or a '
            'training history are ignored.'
        ),
    )
    display_order = models.PositiveSmallIntegerField(
        default=0, help_text='Lower numbers appear first in the dropdown.'
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            'Clear this to retire a paper. Records that already use it keep '
            'their label; the paper simply stops being offered.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['exam_category', 'display_order', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['exam_category', 'code'], name='unique_paper_code_per_category'
            )
        ]
        verbose_name = 'Paper Type'
        verbose_name_plural = 'Paper Types'

    def __str__(self):
        return f'{self.get_exam_category_display()} - {self.name}'

    @property
    def terms(self):
        """The detection phrases, one per line, blank lines dropped."""
        return [
            line.strip()
            for line in (self.detection_terms or '').splitlines()
            if line.strip()
        ]


class Paper(models.TextChoices):
    """Legacy per-paper scheduling values.

    Superseded by PaperType: an application now names the single paper it is
    for, rather than one examination covering several. Kept so the ExamPaper
    rows written under the old two-paper Flight Dispatch model still render.
    """

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
    exam_category = models.CharField(
        max_length=32, choices=ExamCategory.choices, db_index=True
    )
    # Held separately from the category, never combined into one string, so
    # scheduling, reporting, searching and filtering can all work on either.
    # Blank only on records created before papers were captured.
    paper_type = models.CharField(max_length=32, blank=True, db_index=True)

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
            models.Index(fields=['exam_date', 'exam_category']),
            models.Index(fields=['exam_category', 'paper_type']),
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
    def exam_category_display(self):
        return self.get_exam_category_display()

    @property
    def paper_type_label(self):
        """The paper's configured name, for the slip and every listing."""
        from .paper_types import label_for

        return label_for(self.exam_category, self.paper_type)

    @property
    def has_papers(self):
        """True only for legacy records written under the old two-paper model.

        An examination now names the single paper it is for, so nothing new
        creates ExamPaper rows. Reading the prefetched relation rather than
        querying keeps the slip and record list at one query.
        """
        return bool(self.papers.all())

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
