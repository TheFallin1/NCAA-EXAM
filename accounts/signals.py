from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def create_default_groups(sender, **kwargs):
    if sender.name != 'accounts':
        return
    Group.objects.get_or_create(name=settings.GROUP_EXAMINATION_OFFICER)
    Group.objects.get_or_create(name=settings.GROUP_SYSTEM_ADMIN)
