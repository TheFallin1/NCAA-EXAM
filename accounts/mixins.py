from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .utils import is_system_admin_user


class OfficerRequiredMixin(LoginRequiredMixin):
    """Allow authenticated users in Examination Officer or System Admin groups."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.is_superuser:
            return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)
        groups = request.user.groups.values_list('name', flat=True)
        allowed = {settings.GROUP_EXAMINATION_OFFICER, settings.GROUP_SYSTEM_ADMIN}
        if not allowed.intersection(set(groups)):
            raise PermissionDenied('You must be an examination officer to access this system.')
        profile = getattr(request.user, 'officer_profile', None)
        if profile and not profile.is_active_officer and not request.user.is_superuser:
            raise PermissionDenied('Your officer account has been deactivated.')
        return super(LoginRequiredMixin, self).dispatch(request, *args, **kwargs)


class SystemAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = 'system:login'

    def test_func(self):
        return is_system_admin_user(self.request.user)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return redirect('system:login')
        return super().handle_no_permission()
