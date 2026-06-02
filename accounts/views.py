from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from .utils import is_system_admin_user


class AdminAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'admin_required': 'Please sign in with a system administrator account.',
    }

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not is_system_admin_user(user):
            raise ValidationError(
                self.error_messages['admin_required'],
                code='admin_required',
            )


@method_decorator([csrf_protect, never_cache], name='dispatch')
class OfficerLoginView(LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy('dashboard:home')


@method_decorator([csrf_protect, never_cache], name='dispatch')
class AdminLoginView(LoginView):
    authentication_form = AdminAuthenticationForm
    template_name = 'accounts/admin_login.html'
    redirect_authenticated_user = False

    def dispatch(self, request, *args, **kwargs):
        if is_system_admin_user(request.user):
            return redirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy('system:portal')


class OfficerLogoutView(LogoutView):
    next_page = reverse_lazy('accounts:login')
