import json

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from accounts.mixins import OfficerRequiredMixin
from dashboard.audit import log_activity
from dashboard.models import ActivityLog
from exams import paper_types

from .forms import (
    CandidateReviewFormSet,
    ProcessApplicationForm,
    ReviewForm,
    ScheduleStepForm,
)
from .models import (
    Application,
    ApplicationDocument,
    DocumentKind,
    ProcessingStatus,
)
from .services.confirmation import (
    ConfirmationError,
    apply_schedule,
    confirm,
    duplicate_receipt_match,
)
from .services.documents import sha256_of, validate_upload
from .services.jobs import queue_application


class ApplicationListView(OfficerRequiredMixin, ListView):
    """Applications in progress, so an officer can pick work back up."""

    model = Application
    template_name = 'applications/application_list.html'
    context_object_name = 'applications'
    paginate_by = 25

    def get_queryset(self):
        queryset = Application.objects.select_related('created_by')
        status = self.request.GET.get('status', '')
        query = self.request.GET.get('q', '').strip()
        if status:
            queryset = queryset.filter(processing_status=status)
        if query:
            queryset = queryset.filter(reference__icontains=query)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = ProcessingStatus.choices
        context['filters'] = {
            'status': self.request.GET.get('status', ''),
            'q': self.request.GET.get('q', ''),
        }
        return context


class ProcessApplicationView(OfficerRequiredMixin, View):
    """Step 1: select the examination category and paper, and provide both
    documents."""

    template_name = 'applications/process_application.html'

    def get(self, request):
        return render(request, self.template_name, self._context(ProcessApplicationForm()))

    def post(self, request):
        form = ProcessApplicationForm(request.POST, request.FILES)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))

        application = Application.objects.create(
            exam_category=form.cleaned_data['exam_category'],
            paper_type=form.cleaned_data['paper_type'],
            created_by=request.user,
        )
        log_activity(
            request,
            ActivityLog.Action.APPLICATION_STARTED,
            application,
            description=(
                f'{application.reference}: processing started for '
                f'{application.exam_category_label} - {application.paper_type_label}'
            ),
            metadata={
                'exam_category': application.exam_category,
                'paper_type': application.paper_type,
            },
        )

        self._store(request, application, DocumentKind.LETTER, form.cleaned_data['application_letter'])
        self._store(request, application, DocumentKind.RECEIPT, form.cleaned_data['receipt'])

        queue_application(application, request=request)
        return redirect('applications:review', pk=application.pk)

    def _context(self, form):
        # The catalogue drives the dependent dropdown in the browser, so a
        # paper added or renamed in the admin shows up without a code change.
        return {
            'form': form,
            'paper_catalogue': json.dumps(paper_types.catalogue()),
        }

    def _store(self, request, application, kind, uploaded):
        _, content_type = validate_upload(uploaded)
        document = ApplicationDocument.objects.create(
            application=application,
            kind=kind,
            file=uploaded,
            original_name=(uploaded.name or '')[:255],
            content_type=content_type,
            byte_size=uploaded.size,
            sha256=sha256_of(uploaded),
        )
        log_activity(
            request,
            ActivityLog.Action.DOCUMENT_UPLOADED,
            document,
            description=(
                f'{application.reference}: {document.get_kind_display()} '
                f'({document.size_display})'
            ),
            metadata={'sha256': document.sha256, 'content_type': content_type},
        )
        return document


class ApplicationStatusView(OfficerRequiredMixin, View):
    """Polled by the review page while OCR runs."""

    def get(self, request, pk):
        application = get_object_or_404(Application, pk=pk)
        return JsonResponse({
            'status': application.processing_status,
            'status_display': application.get_processing_status_display(),
            'is_processing': application.is_processing,
            'error': application.error_message,
        })


class ApplicationReviewView(OfficerRequiredMixin, View):
    """Step 3: officer verification of everything OCR produced."""

    template_name = 'applications/review.html'

    def get(self, request, pk):
        application = self._application(pk)
        if application.processing_status in (
            ProcessingStatus.CONFIRMED,
            ProcessingStatus.SCHEDULED,
        ):
            return redirect('applications:schedule', pk=application.pk)
        return render(request, self.template_name, self._context(request, application))

    def post(self, request, pk):
        application = self._application(pk)
        if application.processing_status != ProcessingStatus.REVIEW:
            messages.error(
                request,
                'This application cannot be edited in its current state '
                f'({application.get_processing_status_display()}).',
            )
            return redirect('applications:review', pk=application.pk)

        review_form = ReviewForm(request.POST)
        formset = CandidateReviewFormSet(
            request.POST, queryset=application.extracted_candidates.all()
        )

        if not (review_form.is_valid() and formset.is_valid()):
            return render(
                request,
                self.template_name,
                self._context(request, application, review_form, formset),
            )

        self._save_corrections(request, application, review_form, formset)

        if request.POST.get('action') != 'confirm':
            messages.success(request, 'Corrections saved.')
            return redirect('applications:review', pk=application.pk)

        application.refresh_from_db()
        try:
            created = confirm(
                application,
                request=request,
                override_duplicate_receipt=review_form.cleaned_data.get(
                    'confirm_duplicate_receipt'
                ),
            )
        except ConfirmationError as exc:
            messages.error(request, str(exc))
            return redirect('applications:review', pk=application.pk)

        messages.success(
            request,
            f'{len(created)} examination ID(s) generated. Now set the '
            'examination schedule.',
        )
        return redirect('applications:schedule', pk=application.pk)

    # -- helpers -----------------------------------------------------------
    def _application(self, pk):
        return get_object_or_404(
            Application.objects.prefetch_related('documents', 'extracted_candidates'),
            pk=pk,
        )

    def _save_corrections(self, request, application, review_form, formset):
        changes = []
        for form in formset:
            candidate = form.instance
            new_name = form.cleaned_data.get('corrected_name', '')

            if form.is_new_row:
                # A row the officer added because OCR missed someone.
                if not new_name:
                    continue
                candidate.application = application
                candidate.raw_name = ''
                candidate.position = self._next_position(application)
                candidate.needs_review = False
                candidate.is_included = form.cleaned_data.get('is_included', True)
                candidate.corrected_name = new_name
                candidate.save()
                changes.append({'added': new_name})
                continue

            # The before-values must come from the form's initial data, not
            # from the instance: ModelForm._post_clean() has already copied the
            # submitted values onto form.instance by this point, so comparing
            # against it would always report "no change" and the audit trail
            # would silently lose every correction.
            before_name = (form.initial.get('corrected_name') or '').strip()
            before_included = bool(form.initial.get('is_included'))

            candidate.corrected_name = new_name
            candidate.is_included = bool(form.cleaned_data.get('is_included'))
            candidate.save(update_fields=['corrected_name', 'is_included'])

            if candidate.name != before_name:
                changes.append({
                    'position': candidate.position,
                    'from': before_name,
                    'to': candidate.name,
                })
            if candidate.is_included != before_included:
                changes.append({
                    'position': candidate.position,
                    'included': candidate.is_included,
                })

        receipt_before = application.receipt_number
        application.receipt_number = review_form.cleaned_data['receipt_number']
        application.company_name = review_form.cleaned_data.get('company_name', '')
        application.save(update_fields=['receipt_number', 'company_name', 'updated_at'])

        if receipt_before != application.receipt_number:
            changes.append({
                'receipt_number': {
                    'from': receipt_before,
                    'to': application.receipt_number,
                }
            })

        if changes:
            log_activity(
                request,
                ActivityLog.Action.OCR_EDITED,
                application,
                description=(
                    f'{application.reference}: {len(changes)} correction(s) '
                    'made to the extracted information'
                ),
                metadata={'changes': changes},
            )

    def _next_position(self, application):
        last = application.extracted_candidates.order_by('-position').first()
        return (last.position + 1) if last else 1

    def _context(self, request, application, review_form=None, formset=None):
        if review_form is None:
            review_form = ReviewForm(initial={
                'receipt_number': application.receipt_number,
                'company_name': application.company_name,
            })
        if formset is None:
            formset = CandidateReviewFormSet(
                queryset=application.extracted_candidates.all()
            )
        return {
            'application': application,
            'review_form': review_form,
            'formset': formset,
            'duplicate_receipt': duplicate_receipt_match(application),
            'status_url': reverse('applications:status', kwargs={'pk': application.pk}),
        }


class ApplicationRetryView(OfficerRequiredMixin, View):
    """Re-run OCR after a failure or a rescan."""

    def post(self, request, pk):
        application = get_object_or_404(Application, pk=pk)
        if application.processing_status in (
            ProcessingStatus.CONFIRMED,
            ProcessingStatus.SCHEDULED,
        ):
            messages.error(request, 'This application has already been confirmed.')
            return redirect('applications:review', pk=application.pk)

        if not application.has_both_documents:
            messages.error(
                request,
                'Both documents are required: missing '
                + ', '.join(application.missing_documents)
                + '.',
            )
            return redirect('applications:review', pk=application.pk)

        queue_application(application, request=request)
        messages.info(request, 'The documents are being processed again.')
        return redirect('applications:review', pk=application.pk)


class ApplicationScheduleView(OfficerRequiredMixin, View):
    """Step 4: schedule the confirmed examination."""

    template_name = 'applications/schedule.html'

    def get(self, request, pk):
        application = self._application(pk)
        return render(
            request, self.template_name, self._context(application, self._form(application))
        )

    def post(self, request, pk):
        application = self._application(pk)
        form = self._form(application, data=request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(application, form))

        try:
            apply_schedule(application, form.schedule(), request=request)
        except ConfirmationError as exc:
            messages.error(request, str(exc))
            return render(request, self.template_name, self._context(application, form))

        messages.success(
            request,
            'Examination scheduled. The examination slips are ready to print.',
        )
        return redirect('slips:application_batch', pk=application.pk)

    def _application(self, pk):
        application = get_object_or_404(
            Application.objects.prefetch_related('exam_records__papers'), pk=pk
        )
        if application.processing_status not in (
            ProcessingStatus.CONFIRMED,
            ProcessingStatus.SCHEDULED,
        ):
            raise Http404('This application has not been confirmed yet.')
        return application

    def _form(self, application, data=None):
        return ScheduleStepForm(data)

    def _context(self, application, form):
        return {
            'application': application,
            'form': form,
            'exams': application.exam_records.all(),
        }


class ApplicationDocumentView(OfficerRequiredMixin, View):
    """Serve a scanned document to an authenticated officer only.

    Documents live outside the static and media roots, so this view is the
    only route to them.
    """

    def get(self, request, pk):
        document = get_object_or_404(
            ApplicationDocument.objects.select_related('application'), pk=pk
        )

        accel_header = settings.PRIVATE_MEDIA_ACCEL_HEADER
        if accel_header:
            # Hand off to the front-end server, which serves the file from an
            # internal-only location.
            response = HttpResponse(content_type=document.content_type)
            response[accel_header] = (
                settings.PRIVATE_MEDIA_ACCEL_PREFIX.rstrip('/') + '/' + document.file.name
            )
        else:
            response = FileResponse(
                document.file.open('rb'), content_type=document.content_type
            )

        response['Content-Disposition'] = (
            f'inline; filename="{document.get_kind_display()}"'
        )
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
