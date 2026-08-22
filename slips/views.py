from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic import DetailView, ListView

from accounts.mixins import OfficerRequiredMixin
from dashboard.audit import log_activity
from dashboard.models import ActivityLog
from exams.models import ExamSchedule

from .models import SlipRecord
from .utils import get_slip_context, render_slip_pdf, render_slips_pdf


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

    def get_queryset(self):
        return ExamSchedule.objects.select_related('scheduled_by').prefetch_related(
            'papers'
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['slip_record'] = SlipRecord.record_preview(self.object, self.request.user)
        ctx.update(get_slip_context(self.object, self.request))
        return ctx


class SlipPDFView(OfficerRequiredMixin, View):
    def get(self, request, pk):
        exam = get_object_or_404(
            ExamSchedule.objects.prefetch_related('papers'), pk=pk
        )
        try:
            pdf_bytes = render_slip_pdf(exam, request)
        except Exception as exc:
            return HttpResponse(
                f'PDF generation failed: {exc}',
                status=500,
                content_type='text/plain',
            )
        SlipRecord.record_pdf_download(exam, request.user)
        log_activity(
            request,
            ActivityLog.Action.SLIP_GENERATED,
            exam,
            model_name='ExamSchedule',
            description=f'Slip PDF downloaded for {exam.exam_number}',
        )
        filename = f'NCAA_Exam_Slip_{_safe(exam.exam_number)}.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class ApplicationSlipBatchView(OfficerRequiredMixin, View):
    """Every slip for one application, printable in a single pass."""

    template_name = 'slips/slip_batch.html'

    def get(self, request, pk):
        application, exams = _application_exams(pk)
        slips = []
        for exam in exams:
            SlipRecord.record_preview(exam, request.user)
            slips.append(get_slip_context(exam, request))
        return render(
            request,
            self.template_name,
            {'application': application, 'slips': slips, 'exams': exams},
        )


class ApplicationSlipBatchPDFView(OfficerRequiredMixin, View):
    """All slips for one application as a single PDF, one page per candidate."""

    def get(self, request, pk):
        application, exams = _application_exams(pk)
        if not exams:
            return HttpResponse(
                'This application has no examination records.',
                status=404,
                content_type='text/plain',
            )
        try:
            pdf_bytes = render_slips_pdf(exams, request)
        except Exception as exc:
            return HttpResponse(
                f'PDF generation failed: {exc}',
                status=500,
                content_type='text/plain',
            )

        for exam in exams:
            SlipRecord.record_pdf_download(exam, request.user)
        log_activity(
            request,
            ActivityLog.Action.SLIP_GENERATED,
            application,
            description=(
                f'{application.reference}: {len(exams)} slip(s) downloaded as one PDF'
            ),
            metadata={'candidates': len(exams)},
        )

        filename = f'NCAA_Exam_Slips_{_safe(application.reference)}.pdf'
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


def _application_exams(pk):
    from applications.models import Application

    application = get_object_or_404(Application, pk=pk)
    exams = list(
        application.exam_records.select_related('scheduled_by')
        .prefetch_related('papers')
        .order_by('candidate_name')
    )
    return application, exams


def _safe(value):
    """Filename-safe form of an identifier that contains slashes."""
    return ''.join(
        character if character.isalnum() or character in '-_' else '-'
        for character in str(value)
    )
