from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from exams.models import ExamSchedule, ExamType


def get_dashboard_stats():
    today = timezone.localdate()
    upcoming_end = today + timedelta(days=7)

    base_qs = ExamSchedule.objects.all()
    total = base_qs.count()
    today_count = base_qs.filter(exam_date=today).count()
    upcoming_count = base_qs.filter(
        exam_date__gt=today,
        exam_date__lte=upcoming_end,
    ).count()

    by_type = (
        base_qs.values('exam_type')
        .annotate(count=Count('id'))
        .order_by('exam_type')
    )
    type_labels = dict(ExamType.choices)
    chart_labels = []
    chart_data = []
    for row in by_type:
        chart_labels.append(type_labels.get(row['exam_type'], row['exam_type']))
        chart_data.append(row['count'])

    recent = (
        base_qs.select_related('scheduled_by')
        .order_by('-created_at')[:10]
    )

    return {
        'total': total,
        'today_count': today_count,
        'upcoming_count': upcoming_count,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'recent': recent,
    }


def get_calendar_events(year, month):
    """Return dict of day -> count for a given month."""
    from calendar import monthrange

    start = timezone.datetime(year, month, 1).date()
    _, last_day = monthrange(year, month)
    end = timezone.datetime(year, month, last_day).date()

    rows = (
        ExamSchedule.objects.filter(exam_date__gte=start, exam_date__lte=end)
        .values('exam_date')
        .annotate(count=Count('id'))
    )
    return {str(r['exam_date']): r['count'] for r in rows}
