from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import DetailView, ListView

from accounts.mixins import OfficerRequiredMixin
from exams.models import ExamSchedule

from .models import SlipRecord
from .utils import get_slip_context, render_slip_pdf


class SlipRecordListView(OfficerRequiredMixin, ListView):
    model = SlipRecord
    template_name = 'slips/slip_record_list.html'
    context_object_name = 'slip_records'
    paginate_by = 25

    def get_queryset(self):
        qs = SlipRecord.objects.select_related('exam', 'created_by')
        q = self.request.GET.get('q', '').strip()
        date_from = self.request.GET.get('date_from', '')
        date_to = self.request.GET.get('date_to', '')

        if q:
            qs = qs.filter(
                Q(exam__candidate_name__icontains=q)
                | Q(exam__exam_number__icontains=q)
                | Q(exam__receipt_number__icontains=q)
                | Q(exam__company_name__icontains=q)
            )
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['total_slips'] = self.get_queryset().count()
        ctx['filters'] = {
            'q': self.request.GET.get('q', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }
        return ctx


class SlipDetailView(OfficerRequiredMixin, DetailView):
    model = ExamSchedule
    template_name = 'slips/slip_preview.html'
    context_object_name = 'exam'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['slip_record'] = SlipRecord.record_preview(self.object, self.request.user)
        ctx.update(get_slip_context(self.object, self.request))
        return ctx


class SlipPDFView(OfficerRequiredMixin, View):
    def get(self, request, pk):
        exam = get_object_or_404(ExamSchedule, pk=pk)
        try:
            pdf_bytes = render_slip_pdf(exam, request)
        except Exception as exc:
            return HttpResponse(
                f'PDF generation failed: {exc}',
                status=500,
                content_type='text/plain',
            )
        SlipRecord.record_pdf_download(exam, request.user)
        filename = f'NCAA_Exam_Slip_{exam.exam_number}.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response
