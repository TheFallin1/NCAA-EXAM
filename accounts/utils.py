from django.conf import settings


def is_system_admin_user(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=settings.GROUP_SYSTEM_ADMIN).exists()
