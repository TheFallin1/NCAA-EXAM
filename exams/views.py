from django.contrib import messages
from django.db.models import F, Q
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from accounts.mixins import OfficerRequiredMixin

from .forms import ExamScheduleForm
from .models import ExamSchedule, ExamType


class ExamScheduleCreateView(OfficerRequiredMixin, CreateView):
    model = ExamSchedule
    form_class = ExamScheduleForm
    template_name = 'exams/schedule_form.html'

    def form_valid(self, form):
        form.instance.scheduled_by = self.request.user
        form.instance._request = self.request
        self.object = form.save()
        messages.success(self.request, 'Examination scheduled successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('slips:detail', kwargs={'pk': self.object.pk})


class ExamListView(OfficerRequiredMixin, ListView):
    model = ExamSchedule
    template_name = 'exams/exam_list.html'
    context_object_name = 'exams'
    paginate_by = 25

    def get_queryset(self):
        qs = ExamSchedule.objects.select_related('scheduled_by')
        q = self.request.GET.get('q', '').strip()
        exam_type = self.request.GET.get('exam_type', '')
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')
        sort = self.request.GET.get('sort', '-exam_date')

        if q:
            qs = qs.filter(
                Q(candidate_name__icontains=q)
                | Q(exam_number__icontains=q)
                | Q(receipt_number__icontains=q)
                | Q(company_name__icontains=q)
                | Q(exam_type__icontains=q)
            )
        if exam_type:
            qs = qs.filter(exam_type=exam_type)
        if date_from:
            qs = qs.filter(exam_date__gte=date_from)
        if date_to:
            qs = qs.filter(exam_date__lte=date_to)

        allowed_sorts = {
            'exam_date': 'exam_date',
            '-exam_date': '-exam_date',
            'candidate_name': 'candidate_name',
            '-candidate_name': '-candidate_name',
            'created_at': 'created_at',
            '-created_at': '-created_at',
        }
        field = allowed_sorts.get(sort, '-exam_date')
        if field.lstrip('-') == 'exam_date':
            # Records confirmed but not yet scheduled have no date. Order them
            # explicitly so SQLite and PostgreSQL agree on where NULLs land.
            descending = field.startswith('-')
            expression = F('exam_date').desc(nulls_last=True) if descending else F('exam_date').asc(nulls_first=True)
            qs = qs.order_by(expression, '-exam_time')
        else:
            qs = qs.order_by(field, '-exam_time')
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['exam_types'] = ExamType.choices
        ctx['filters'] = {
            'q': self.request.GET.get('q', ''),
            'exam_type': self.request.GET.get('exam_type', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'sort': self.request.GET.get('sort', '-exam_date'),
        }
        return ctx


class ExamUpdateView(OfficerRequiredMixin, UpdateView):
    model = ExamSchedule
    form_class = ExamScheduleForm
    template_name = 'exams/schedule_form.html'
    context_object_name = 'exam'

    def form_valid(self, form):
        form.instance._request = self.request
        self.object = form.save()
        messages.success(self.request, 'Examination record updated.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('slips:detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['is_edit'] = True
        return ctx


class ExamDeleteView(OfficerRequiredMixin, DeleteView):
    model = ExamSchedule
    template_name = 'exams/exam_confirm_delete.html'
    success_url = reverse_lazy('exams:list')

    def form_valid(self, form):
        # Since Django 4.0 DeleteView is form-based and POST routes through
        # form_valid, not delete(). Attaching the request here is what lets the
        # audit trail record who removed the record and from where.
        self.object._request = self.request
        messages.success(self.request, 'Examination record deleted.')
        return super().form_valid(form)
