"""Audit hooks for the application-processing workflow."""
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from dashboard.audit import log_activity


@receiver(user_logged_in)
def log_officer_login(sender, request, user, **kwargs):
    log_activity(
        request,
        action='login',
        obj=user,
        model_name='User',
        description=f'{user.username} signed in',
    )
