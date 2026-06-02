from django.urls import path

from .views import (
    ExamDeleteView,
    ExamListView,
    ExamScheduleCreateView,
    ExamUpdateView,
)

app_name = 'exams'

urlpatterns = [
    path('', ExamListView.as_view(), name='list'),
    path('schedule/', ExamScheduleCreateView.as_view(), name='schedule'),
    path('<uuid:pk>/edit/', ExamUpdateView.as_view(), name='edit'),
    path('<uuid:pk>/delete/', ExamDeleteView.as_view(), name='delete'),
]
