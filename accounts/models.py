from django.conf import settings
from django.db import models


class OfficerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='officer_profile',
    )
    employee_id = models.CharField(max_length=50, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    is_active_officer = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Officer Profile'
        verbose_name_plural = 'Officer Profiles'

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username}'
