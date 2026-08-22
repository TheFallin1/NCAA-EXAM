from django.urls import path

from .views import (
    ApplicationSlipBatchPDFView,
    ApplicationSlipBatchView,
    SlipDetailView,
    SlipPDFView,
    SlipRecordListView,
)

app_name = 'slips'

urlpatterns = [
    path('records/', SlipRecordListView.as_view(), name='records'),
    path(
        'application/<uuid:pk>/',
        ApplicationSlipBatchView.as_view(),
        name='application_batch',
    ),
    path(
        'application/<uuid:pk>/pdf/',
        ApplicationSlipBatchPDFView.as_view(),
        name='application_batch_pdf',
    ),
    path('<uuid:pk>/', SlipDetailView.as_view(), name='detail'),
    path('<uuid:pk>/pdf/', SlipPDFView.as_view(), name='pdf'),
]
