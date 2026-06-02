from django.conf import settings


def site_settings(request):
    is_system_admin = False
    if request.user.is_authenticated:
        if request.user.is_superuser:
            is_system_admin = True
        else:
            is_system_admin = request.user.groups.filter(
                name=settings.GROUP_SYSTEM_ADMIN
            ).exists()

    return {
        'NCAA_FULL_NAME': settings.NCAA_FULL_NAME,
        'NCAA_LOGO_URL': settings.NCAA_LOGO_URL,
        'is_system_admin': is_system_admin,
    }
