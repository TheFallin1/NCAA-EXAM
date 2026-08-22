from datetime import date

from django.contrib import messages
from django.contrib.auth.models import Group, User
from django.contrib.auth.forms import SetPasswordForm
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, ListView, TemplateView, View

from accounts.mixins import OfficerRequiredMixin, SystemAdminRequiredMixin
from accounts.models import OfficerProfile
from dashboard.models import ActivityLog
from dashboard.services import (
    get_calendar_events,
    get_dashboard_stats,
    normalise_month,
)
from exams.models import ExamSchedule

import csv


class DashboardHomeView(OfficerRequiredMixin, TemplateView):
    template_name = 'dashboard/home.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        stats = get_dashboard_stats()
        ctx.update(stats)
        today = date.today()
        year, month = normalise_month(
            self.request.GET.get('year', today.year),
            self.request.GET.get('month', today.month),
        )
        ctx['calendar_year'] = year
        ctx['calendar_month'] = month
        ctx['calendar_events'] = get_calendar_events(year, month)
        import json

        ctx['chart_labels_json'] = json.dumps(stats['chart_labels'])
        ctx['chart_data_json'] = json.dumps(stats['chart_data'])
        return ctx


class StatsAPIView(OfficerRequiredMixin, View):
    def get(self, request):
        from django.http import JsonResponse

        stats = get_dashboard_stats()
        return JsonResponse({
            'total': stats['total'],
            'today_count': stats['today_count'],
            'upcoming_count': stats['upcoming_count'],
            'chart_labels': stats['chart_labels'],
            'chart_data': stats['chart_data'],
        })


class CalendarAPIView(OfficerRequiredMixin, View):
    def get(self, request):
        from django.http import JsonResponse

        year, month = normalise_month(
            request.GET.get('year'), request.GET.get('month')
        )
        return JsonResponse(get_calendar_events(year, month))


class SystemPortalView(SystemAdminRequiredMixin, TemplateView):
    template_name = 'dashboard/system_portal.html'


class OfficerListView(SystemAdminRequiredMixin, ListView):
    model = User
    template_name = 'dashboard/officer_list.html'
    context_object_name = 'officers'
    paginate_by = 20

    def get_queryset(self):
        return (
            User.objects.filter(officer_profile__isnull=False)
            .select_related('officer_profile')
            .prefetch_related('groups')
            .order_by('username')
        )


class ActivityLogListView(SystemAdminRequiredMixin, ListView):
    model = ActivityLog
    template_name = 'dashboard/activity_log.html'
    context_object_name = 'logs'
    paginate_by = 50


class OfficerCreateView(SystemAdminRequiredMixin, TemplateView):
    template_name = 'dashboard/officer_form.html'

    def get(self, request, *args, **kwargs):
        return self.render_to_response(self.get_context_data(**kwargs))

    def post(self, request):
        from django.conf import settings

        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        email = request.POST.get('email', '')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        employee_id = request.POST.get('employee_id', '')
        phone = request.POST.get('phone', '')
        is_admin = request.POST.get('is_admin') == 'on'

        if not username or not password:
            messages.error(request, 'Username and password are required.')
            return redirect('system:officer_create')

        if User.objects.filter(username=username).exists():
            messages.error(request, f'User "{username}" already exists.')
            return redirect('system:officer_create')

        user = User.objects.create_user(
            username=username,
            password=password,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        OfficerProfile.objects.create(
            user=user,
            employee_id=employee_id,
            phone=phone,
        )
        officer_group, _ = Group.objects.get_or_create(
            name=settings.GROUP_EXAMINATION_OFFICER
        )
        user.groups.add(officer_group)
        if is_admin:
            admin_group, _ = Group.objects.get_or_create(
                name=settings.GROUP_SYSTEM_ADMIN
            )
            user.groups.add(admin_group)
            user.is_staff = True
            user.save(update_fields=['is_staff'])

        messages.success(request, f'Officer "{username}" created.')
        return redirect('system:officer_list')


class OfficerPasswordResetView(SystemAdminRequiredMixin, FormView):
    template_name = 'dashboard/officer_password_reset.html'
    form_class = SetPasswordForm
    success_url = reverse_lazy('system:officer_list')

    def dispatch(self, request, *args, **kwargs):
        self.officer = get_object_or_404(User, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.officer
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for name in ('new_password1', 'new_password2'):
            if name in form.fields:
                form.fields[name].widget.attrs.update({'class': 'form-input mt-1'})
        return form

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['officer'] = self.officer
        return ctx

    def form_valid(self, form):
        form.save()
        messages.success(self.request, f'Password reset for {self.officer.username}.')
        return super().form_valid(form)


class OfficerToggleActiveView(SystemAdminRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk, officer_profile__isnull=False)
        profile = user.officer_profile
        profile.is_active_officer = not profile.is_active_officer
        profile.save(update_fields=['is_active_officer'])
        status = 'activated' if profile.is_active_officer else 'deactivated'
        messages.success(request, f'Officer {user.username} {status}.')
        return redirect('system:officer_list')


class ExportExamsCSVView(OfficerRequiredMixin, View):
    def get(self, request):
        qs = ExamSchedule.objects.select_related('scheduled_by').order_by('-exam_date')
        exam_type = request.GET.get('exam_type', '')
        if exam_type:
            qs = qs.filter(exam_type=exam_type)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="ncaa_exam_records.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Candidate', 'Exam Number', 'Receipt', 'Company', 'Type',
            'Date', 'Time', 'Venue', 'Officer', 'Created',
        ])
        for obj in qs:
            writer.writerow([
                obj.candidate_name,
                obj.exam_number,
                obj.receipt_number,
                obj.company_name,
                obj.get_exam_type_display(),
                obj.exam_date,
                obj.exam_time,
                obj.venue,
                obj.scheduled_by.username,
                obj.created_at,
            ])
        return response
