from django.urls import path, include

from .views import DashboardHomeView, ExportExamsCSVView

app_name = 'dashboard'

urlpatterns = [
    path('', DashboardHomeView.as_view(), name='home'),
    path('export/csv/', ExportExamsCSVView.as_view(), name='export_csv'),
]

# System admin routes mounted at /system/ via config.urls
