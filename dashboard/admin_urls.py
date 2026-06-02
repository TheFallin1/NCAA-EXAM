from django.urls import path

from accounts.views import AdminLoginView

from .views import (
    ActivityLogListView,
    OfficerCreateView,
    OfficerListView,
    OfficerPasswordResetView,
    OfficerToggleActiveView,
    SystemPortalView,
)

app_name = 'system'

urlpatterns = [
    path('login/', AdminLoginView.as_view(), name='login'),
    path('', SystemPortalView.as_view(), name='portal'),
    path('officers/', OfficerListView.as_view(), name='officer_list'),
    path('officers/create/', OfficerCreateView.as_view(), name='officer_create'),
    path('officers/<int:pk>/reset-password/', OfficerPasswordResetView.as_view(), name='officer_reset_password'),
    path('officers/<int:pk>/toggle-active/', OfficerToggleActiveView.as_view(), name='officer_toggle_active'),
    path('activity/', ActivityLogListView.as_view(), name='activity_log'),
]
