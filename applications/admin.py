from django.contrib import admin

from .models import Application, ApplicationDocument, ExtractedCandidate


class ApplicationDocumentInline(admin.TabularInline):
    model = ApplicationDocument
    extra = 0
    readonly_fields = ('sha256', 'byte_size', 'page_count', 'engine', 'duration_ms')


class ExtractedCandidateInline(admin.TabularInline):
    model = ExtractedCandidate
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'exam_type', 'detected_exam_type', 'receipt_number',
        'processing_status', 'created_by', 'created_at',
    )
    list_filter = ('processing_status', 'exam_type')
    search_fields = ('reference', 'receipt_number', 'company_name')
    readonly_fields = ('id', 'reference', 'created_at', 'updated_at')
    inlines = [ApplicationDocumentInline, ExtractedCandidateInline]
