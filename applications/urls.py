from django.urls import path

from .views import (
    ApplicationDocumentView,
    ApplicationListView,
    ApplicationRetryView,
    ApplicationReviewView,
    ApplicationScheduleView,
    ApplicationStatusView,
    ProcessApplicationView,
)

app_name = 'applications'

urlpatterns = [
    path('', ApplicationListView.as_view(), name='list'),
    path('process/', ProcessApplicationView.as_view(), name='process'),
    path('<uuid:pk>/review/', ApplicationReviewView.as_view(), name='review'),
    path('<uuid:pk>/status/', ApplicationStatusView.as_view(), name='status'),
    path('<uuid:pk>/retry/', ApplicationRetryView.as_view(), name='retry'),
    path('<uuid:pk>/schedule/', ApplicationScheduleView.as_view(), name='schedule'),
    path('documents/<uuid:pk>/', ApplicationDocumentView.as_view(), name='document'),
]
