"""Application intake models.

An Application is the paper submission an officer is processing: one letter,
one receipt, and one or more candidates. Nothing here is an official record --
extracted candidates stay in this staging area until the officer confirms them,
at which point exams.ExamSchedule rows are created.
"""
import uuid

from django.conf import settings
from django.db import models

from exams.models import ExamCategory, ExamSchedule

from .services.documents import document_upload_path, private_storage


class ProcessingStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    QUEUED = 'queued', 'Queued for OCR'
    PROCESSING = 'processing', 'OCR in progress'
    FAILED = 'failed', 'OCR failed'
    MISMATCH = 'mismatch', 'Examination category mismatch'
    PAPER_MISMATCH = 'paper_mismatch', 'Paper type mismatch'
    REVIEW = 'review', 'Awaiting verification'
    CONFIRMED = 'confirmed', 'Confirmed'
    SCHEDULED = 'scheduled', 'Scheduled'


class DocumentKind(models.TextChoices):
    LETTER = 'letter', 'Application Letter'
    RECEIPT = 'receipt', 'Payment Receipt'


class Application(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=32, unique=True, blank=True, db_index=True)

    # What the officer chose before any document was read. The two selections
    # are dependent but stored apart: combining them into one string would
    # make every later query -- scheduling, reporting, filtering -- pick a
    # composite value back apart.
    exam_category = models.CharField(
        max_length=32, choices=ExamCategory.choices, db_index=True
    )
    # The PaperType code, valid only in combination with exam_category.
    paper_type = models.CharField(max_length=32, blank=True, db_index=True)

    # What OCR independently found in the letter. Kept separate from the
    # officer's selection so the two can be compared, displayed side by side,
    # and audited.
    detected_exam_category = models.CharField(max_length=32, blank=True)
    detected_exam_category_evidence = models.CharField(max_length=255, blank=True)
    detected_exam_category_ambiguous = models.BooleanField(default=False)

    # Blank means the letter did not say, which is a real outcome rather than
    # a failure: the paper is never guessed from a passing mention.
    detected_paper_type = models.CharField(max_length=32, blank=True)
    detected_paper_type_evidence = models.CharField(max_length=255, blank=True)
    detected_paper_type_ambiguous = models.BooleanField(default=False)

    receipt_number = models.CharField(max_length=64, blank=True, db_index=True)
    receipt_number_confidence = models.FloatField(null=True, blank=True)
    company_name = models.CharField(max_length=255, blank=True)

    processing_status = models.CharField(
        max_length=16,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.DRAFT,
        db_index=True,
    )
    error_message = models.TextField(blank=True)

    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='processed_applications',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['processing_status', '-created_at']),
        ]
        verbose_name = 'Application'
        verbose_name_plural = 'Applications'

    def __str__(self):
        return self.reference or str(self.id)

    def save(self, *args, **kwargs):
        if not self.reference:
            from .services.references import next_application_reference

            self.reference = next_application_reference()
        super().save(*args, **kwargs)

    # -- documents ---------------------------------------------------------
    def document(self, kind):
        for document in self.documents.all():
            if document.kind == kind:
                return document
        return None

    @property
    def letter(self):
        return self.document(DocumentKind.LETTER)

    @property
    def receipt(self):
        return self.document(DocumentKind.RECEIPT)

    @property
    def has_both_documents(self):
        """Both documents are mandatory before any processing may begin."""
        return self.letter is not None and self.receipt is not None

    @property
    def missing_documents(self):
        missing = []
        if self.letter is None:
            missing.append(DocumentKind.LETTER.label)
        if self.receipt is None:
            missing.append(DocumentKind.RECEIPT.label)
        return missing

    # -- workflow state ----------------------------------------------------
    @property
    def is_processing(self):
        return self.processing_status in (
            ProcessingStatus.QUEUED,
            ProcessingStatus.PROCESSING,
        )

    @property
    def is_blocked(self):
        return self.processing_status in (
            ProcessingStatus.FAILED,
            ProcessingStatus.MISMATCH,
            ProcessingStatus.PAPER_MISMATCH,
        )

    @property
    def exam_category_label(self):
        from exams.exam_categories import label_for

        return label_for(self.exam_category)

    @property
    def detected_exam_category_label(self):
        from exams.exam_categories import label_for

        return label_for(self.detected_exam_category) if self.detected_exam_category else ''

    @property
    def paper_type_label(self):
        from exams.paper_types import label_for

        return label_for(self.exam_category, self.paper_type)

    @property
    def detected_paper_type_label(self):
        from exams.paper_types import label_for

        return label_for(self.exam_category, self.detected_paper_type)

    @property
    def paper_type_determined(self):
        """True when OCR could name the paper the letter is for."""
        return bool(self.detected_paper_type)

    @property
    def included_candidates(self):
        return [c for c in self.extracted_candidates.all() if c.is_included]


class ApplicationDocument(models.Model):
    """One scanned document plus the OCR result derived from it."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='documents'
    )
    kind = models.CharField(max_length=16, choices=DocumentKind.choices)

    file = models.FileField(upload_to=document_upload_path, storage=private_storage)
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    byte_size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, db_index=True)

    # OCR output
    page_count = models.PositiveIntegerField(default=0)
    raw_text = models.TextField(blank=True)
    mean_confidence = models.FloatField(null=True, blank=True)
    engine = models.CharField(max_length=64, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    used_text_layer = models.BooleanField(default=False)
    # How the page had to be turned before it could be read.
    rotation_applied = models.PositiveSmallIntegerField(default=0)
    skew_applied = models.FloatField(null=True, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # One letter and one receipt per application, enforced by the database.
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'kind'],
                name='unique_document_kind_per_application',
            )
        ]
        ordering = ['kind']
        verbose_name = 'Application Document'
        verbose_name_plural = 'Application Documents'

    def __str__(self):
        return f'{self.get_kind_display()} for {self.application}'

    @property
    def correction_display(self):
        """What preparation did to the page, for the officer to see."""
        parts = []
        if self.rotation_applied:
            parts.append(f'rotated {self.rotation_applied} degrees')
        if self.skew_applied:
            parts.append(f'deskewed {self.skew_applied:+.1f} degrees')
        return ', '.join(parts)

    @property
    def size_display(self):
        kilobytes = self.byte_size / 1024
        if kilobytes < 1024:
            return f'{kilobytes:.0f} KB'
        return f'{kilobytes / 1024:.1f} MB'


class ExtractedCandidate(models.Model):
    """A candidate name read from the letter, pending officer verification.

    These are not examination records. They exist only so the officer can
    correct OCR mistakes before anything official is created.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='extracted_candidates'
    )
    position = models.PositiveIntegerField()

    raw_name = models.CharField(max_length=255)
    corrected_name = models.CharField(max_length=255, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    needs_review = models.BooleanField(default=False)
    is_included = models.BooleanField(default=True)

    # Set when a matching examination record already exists, so the officer is
    # warned before a second one is created for the same person.
    possible_duplicate_of = models.ForeignKey(
        ExamSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    class Meta:
        ordering = ['position']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'position'], name='unique_candidate_position'
            )
        ]
        verbose_name = 'Extracted Candidate'
        verbose_name_plural = 'Extracted Candidates'

    def __str__(self):
        return self.name

    @property
    def name(self):
        """The name of record: the officer's correction wins over OCR."""
        return (self.corrected_name or self.raw_name).strip()

    @property
    def was_corrected(self):
        return (
            bool(self.corrected_name)
            and self.corrected_name.strip() != self.raw_name.strip()
        )

    @property
    def confidence_display(self):
        return f'{self.confidence:.0f}%' if self.confidence is not None else '--'
