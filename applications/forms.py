from django import forms
from django.forms import modelformset_factory
from django.utils import timezone

from exams.forms import ExamSelectionMixin

from .models import ExtractedCandidate
from .services.documents import DocumentValidationError, validate_upload

_FILE_ACCEPT = '.pdf,.jpg,.jpeg,.png'


class ProcessApplicationForm(ExamSelectionMixin, forms.Form):
    """Step 1: the examination selection plus the two mandatory documents.

    Both documents are required here as well as in the browser, so a submission
    that bypasses the disabled button is still refused.
    """

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._build_exam_selection()
        # Keep the declared order: the two selections lead the form.
        self.order_fields(
            ['exam_category', 'paper_type', 'application_letter', 'receipt']
        )

    def clean(self):
        return self._clean_exam_selection(super().clean())

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


class ScheduleStepForm(forms.Form):
    """Step 4: schedule the confirmed examination.

    One application is for one paper of one category -- Flight Dispatch Paper 1
    is a different examination from Paper 2 -- so there is a single date, time
    and venue, which every candidate on the application shares.
    """

    exam_date = forms.DateField(
        label='Examination date',
        widget=forms.DateInput(attrs={'class': 'form-input', 'type': 'date'}),
    )
    exam_time = forms.TimeField(
        label='Examination time',
        widget=forms.TimeInput(attrs={'class': 'form-input', 'type': 'time'}),
    )
    venue = forms.CharField(
        label='Examination venue',
        max_length=255,
        widget=forms.TextInput(
            attrs={'class': 'form-input', 'placeholder': 'Examination venue'}
        ),
    )

    def clean_exam_date(self):
        value = self.cleaned_data['exam_date']
        if value and value < timezone.localdate():
            raise forms.ValidationError('The examination date cannot be in the past.')
        return value

    def schedule(self):
        """The date/time/venue to write onto every record on the application."""
        return {
            'exam_date': self.cleaned_data['exam_date'],
            'exam_time': self.cleaned_data['exam_time'],
            'venue': self.cleaned_data['venue'],
        }
