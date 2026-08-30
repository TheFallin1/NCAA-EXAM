from django.contrib import admin

from .models import SlipRecord


@admin.register(SlipRecord)
class SlipRecordAdmin(admin.ModelAdmin):
    list_display = (
        'exam_number',
        'candidate_name',
        'exam_category',
        'paper_type',
        'created_by',
        'created_at',
        'preview_count',
        'pdf_download_count',
    )
    list_filter = (
        'created_at', 'pdf_generated_at', 'exam__exam_category',
        'exam__paper_type',
    )
    search_fields = (
        'exam__candidate_name',
        'exam__exam_number',
        'exam__receipt_number',
        'exam__company_name',
    )
    readonly_fields = (
        'exam',
        'created_by',
        'created_at',
        'last_viewed_at',
        'pdf_generated_at',
        'preview_count',
        'pdf_download_count',
    )

    @admin.display(description='Exam #')
    def exam_number(self, obj):
        return obj.exam.exam_number

    @admin.display(description='Candidate')
    def candidate_name(self, obj):
        return obj.exam.candidate_name

    @admin.display(description='Exam Category')
    def exam_category(self, obj):
        return obj.exam.get_exam_category_display()

    @admin.display(description='Paper')
    def paper_type(self, obj):
        return obj.exam.paper_type_label
