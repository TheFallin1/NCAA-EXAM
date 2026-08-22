from django import forms
from django.forms import modelformset_factory
from django.utils import timezone

from exams.exam_types import has_papers
from exams.models import ExamType, Paper

from .models import ExtractedCandidate
from .services.documents import DocumentValidationError, validate_upload

_FILE_ACCEPT = '.pdf,.jpg,.jpeg,.png'


class ProcessApplicationForm(forms.Form):
    """Step 1: examination type plus the two mandatory documents.

    Both documents are required here as well as in the browser, so a submission
    that bypasses the disabled button is still refused.
    """

    exam_type = forms.ChoiceField(
        choices=[('', 'Select examination type')] + list(ExamType.choices),
        widget=forms.Select(attrs={'class': 'form-input'}),
        label='Examination type',
    )
    application_letter = forms.FileField(
        label='Application letter',
        widget=forms.FileInput(attrs={
            'class': 'form-input',
            'accept': _FILE_ACCEPT,
            # Drives the "both documents present" gate on the submit button.
            'x-on:change': 'letter = $event.target.files.length > 0',
        }),
    )
    receipt = forms.FileField(
        label='Payment receipt',
        widget=forms.FileInput(attrs={
            'class': 'form-input',
            'accept': _FILE_ACCEPT,
            'x-on:change': 'receipt = $event.target.files.length > 0',
        }),
    )

    def clean_application_letter(self):
        return self._validate(self.cleaned_data['application_letter'])

    def clean_receipt(self):
        return self._validate(self.cleaned_data['receipt'])

    def _validate(self, uploaded):
        try:
            validate_upload(uploaded)
        except DocumentValidationError as exc:
            raise forms.ValidationError(str(exc)) from exc
        return uploaded


class CandidateReviewForm(forms.ModelForm):
    """One row of the officer verification table."""

    class Meta:
        model = ExtractedCandidate
        fields = ['corrected_name', 'is_included']
        widgets = {
            'corrected_name': forms.TextInput(
                attrs={'class': 'form-input', 'autocomplete': 'off'}
            ),
            'is_included': forms.CheckboxInput(
                attrs={'class': 'h-4 w-4 rounded border-slate-300'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['corrected_name'].required = False
        self.fields['is_included'].required = False
        instance = self.instance
        # Show the OCR reading in the box so the officer edits the text
        # itself rather than retyping it from scratch.
        if instance and not instance._state.adding and not self.initial.get('corrected_name'):
            self.initial['corrected_name'] = instance.name

    @property
    def is_new_row(self):
        # The primary key is a UUID with a default, so it is populated before
        # the row is ever saved. `_state.adding` is what actually distinguishes
        # an unsaved instance here.
        return self.instance._state.adding

    def clean_corrected_name(self):
        return ' '.join((self.cleaned_data.get('corrected_name') or '').split())

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get('corrected_name', '')
        included = cleaned.get('is_included')
        if included and not name and not self.instance.raw_name:
            raise forms.ValidationError(
                'Enter a candidate name or clear the "include" box for this row.'
            )
        return cleaned


CandidateReviewFormSet = modelformset_factory(
    ExtractedCandidate,
    form=CandidateReviewForm,
    extra=2,
    can_delete=False,
)


class ReviewForm(forms.Form):
    """The application-level fields on the verification screen."""

    receipt_number = forms.CharField(
        max_length=64,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
        label='Official Receipt Number',
    )
    company_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'autocomplete': 'off'}),
        label='Company',
    )
    confirm_duplicate_receipt = forms.BooleanField(
        required=False,
        label='I have verified that this is not a duplicate submission',
        widget=forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300'}),
    )

    def clean_receipt_number(self):
        return (self.cleaned_data.get('receipt_number') or '').strip().upper()


class _ScheduleFieldsMixin:
    def _schedule_fields(self, prefix, label):
        return {
            f'{prefix}exam_date': forms.DateField(
                label=f'{label} date',
                widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
            ),
            f'{prefix}exam_time': forms.TimeField(
                label=f'{label} time',
                widget=forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
            ),
            f'{prefix}venue': forms.CharField(
                label=f'{label} venue',
                max_length=255,
                widget=forms.TextInput(
                    attrs={'class': 'form-input', 'placeholder': 'Examination venue'}
                ),
            ),
        }


class ScheduleStepForm(forms.Form, _ScheduleFieldsMixin):
    """Step 4: schedule the confirmed examination.

    Single-sitting examinations get one set of fields. Flight Dispatch gets a
    set per paper, because NCAA sits Paper 1 and Paper 2 on different days --
    with an option to reuse Paper 1's schedule if a combined sitting is ever
    arranged.
    """

    def __init__(self, *args, exam_type=None, shared_default=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.exam_type = exam_type
        self.multi_paper = has_papers(exam_type)

        if self.multi_paper:
            self.fields['share_schedule'] = forms.BooleanField(
                required=False,
                initial=shared_default,
                label='Both papers sit at the same date, time and venue',
                widget=forms.CheckboxInput(
                    attrs={'class': 'h-4 w-4 rounded border-slate-300'}
                ),
            )
            for field, definition in self._schedule_fields('paper_1_', 'Paper 1').items():
                self.fields[field] = definition
            for field, definition in self._schedule_fields('paper_2_', 'Paper 2').items():
                definition.required = False
                self.fields[field] = definition
        else:
            for field, definition in self._schedule_fields('', 'Examination').items():
                self.fields[field] = definition

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()

        if not self.multi_paper:
            self._reject_past(cleaned, 'exam_date', today)
            return cleaned

        if cleaned.get('share_schedule'):
            # Copy Paper 1 across so both papers are stored either way and the
            # slip renders identically regardless of the configuration.
            for suffix in ('exam_date', 'exam_time', 'venue'):
                cleaned[f'paper_2_{suffix}'] = cleaned.get(f'paper_1_{suffix}')
        else:
            for suffix, label in (
                ('exam_date', 'date'),
                ('exam_time', 'time'),
                ('venue', 'venue'),
            ):
                if not cleaned.get(f'paper_2_{suffix}'):
                    self.add_error(
                        f'paper_2_{suffix}',
                        f'Enter the Paper 2 {label}, or tick the shared-schedule box.',
                    )

        self._reject_past(cleaned, 'paper_1_exam_date', today)
        self._reject_past(cleaned, 'paper_2_exam_date', today)
        return cleaned

    def _reject_past(self, cleaned, field, today):
        value = cleaned.get(field)
        if value and value < today:
            self.add_error(field, 'The examination date cannot be in the past.')

    # -- output ------------------------------------------------------------
    def primary_schedule(self):
        if self.multi_paper:
            return None
        return {
            'exam_date': self.cleaned_data['exam_date'],
            'exam_time': self.cleaned_data['exam_time'],
            'venue': self.cleaned_data['venue'],
        }

    def paper_schedules(self):
        if not self.multi_paper:
            return None
        return {
            Paper.PAPER_1: {
                'exam_date': self.cleaned_data['paper_1_exam_date'],
                'exam_time': self.cleaned_data['paper_1_exam_time'],
                'venue': self.cleaned_data['paper_1_venue'],
            },
            Paper.PAPER_2: {
                'exam_date': self.cleaned_data['paper_2_exam_date'],
                'exam_time': self.cleaned_data['paper_2_exam_time'],
                'venue': self.cleaned_data['paper_2_venue'],
            },
        }
