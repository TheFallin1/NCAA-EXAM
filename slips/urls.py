from django.urls import path

from .views import SlipDetailView, SlipPDFView, SlipRecordListView

app_name = 'slips'

urlpatterns = [
    path('records/', SlipRecordListView.as_view(), name='records'),
    path('<uuid:pk>/', SlipDetailView.as_view(), name='detail'),
    path('<uuid:pk>/pdf/', SlipPDFView.as_view(), name='pdf'),
]
