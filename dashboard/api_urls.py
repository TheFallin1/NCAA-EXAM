from django.urls import path

from .views import CalendarAPIView, StatsAPIView

urlpatterns = [
    path('stats/', StatsAPIView.as_view(), name='api_stats'),
    path('calendar/', CalendarAPIView.as_view(), name='api_calendar'),
]
