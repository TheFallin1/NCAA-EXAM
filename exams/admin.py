import csv

from django.contrib import admin
from django.http import HttpResponse

from .models import ExamSchedule


@admin.register(ExamSchedule)
class ExamScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'candidate_name',
        'exam_number',
        'exam_type',
        'exam_date',
        'exam_time',
        'venue',
        'scheduled_by',
        'created_at',
    )
    list_filter = ('exam_type', 'exam_date', 'venue')
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
            'Exam Type', 'Exam Date', 'Exam Time', 'Venue', 'Officer', 'Created',
        ])
        for obj in queryset.select_related('scheduled_by'):
            writer.writerow([
                obj.candidate_name,
                obj.exam_number,
                obj.receipt_number,
                obj.company_name,
                obj.get_exam_type_display(),
                obj.exam_date,
                obj.exam_time,
                obj.venue,
                obj.scheduled_by.username,
                obj.created_at,
            ])
        return response
