import csv

from django.contrib import admin
from django.http import HttpResponse

from .models import ExamSchedule, PaperType


@admin.register(ExamSchedule)
class ExamScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'candidate_name',
        'exam_number',
        'exam_category',
        'paper_type',
        'exam_date',
        'exam_time',
        'venue',
        'scheduled_by',
        'created_at',
    )
    list_filter = ('exam_category', 'paper_type', 'exam_date', 'venue')
    search_fields = (
        'candidate_name',
        'exam_number',
        'receipt_number',
        'company_name',
    )
    readonly_fields = ('id', 'slip_token', 'created_at', 'updated_at')
    date_hierarchy = 'exam_date'
    actions = ['export_as_csv']

    @admin.action(description='Export selected to CSV')
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="exam_schedules.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Candidate Name', 'Exam Number', 'Receipt Number', 'Company',
            'Exam Category', 'Paper', 'Exam Date', 'Exam Time', 'Venue',
            'Officer', 'Created',
        ])
        for obj in queryset.select_related('scheduled_by'):
            writer.writerow([
                obj.candidate_name,
                obj.exam_number,
                obj.receipt_number,
                obj.company_name,
                obj.get_exam_category_display(),
                obj.paper_type_label,
                obj.exam_date,
                obj.exam_time,
                obj.venue,
                obj.scheduled_by.username,
                obj.created_at,
            ])
        return response


@admin.register(PaperType)
class PaperTypeAdmin(admin.ModelAdmin):
    """Where the papers offered under each category are configured.

    Adding a paper, renaming one -- the placeholder AME papers especially --
    or retiring one happens here and takes effect everywhere: the dependent
    dropdown, the OCR detection, the validation and the examination slip.
    """

    list_display = (
        'exam_category', 'name', 'code', 'display_order', 'is_active'
    )
    list_filter = ('exam_category', 'is_active')
    list_editable = ('name', 'display_order', 'is_active')
    search_fields = ('name', 'code', 'detection_terms')
    ordering = ('exam_category', 'display_order', 'name')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('exam_category', 'code', 'name')}),
        ('Dropdown', {'fields': ('display_order', 'is_active')}),
        ('OCR detection', {'fields': ('detection_terms',)}),
        ('Audit', {'fields': ('created_at', 'updated_at')}),
    )
