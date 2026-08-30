from django import forms
from django.core.exceptions import ValidationError

from . import paper_types
from .models import ExamCategory, ExamSchedule


class ExamSelectionMixin:
    """The dependent Examination Category / Paper Type pair.

    The two selections are dependent, so the pair is what gets validated, not
    each field alone. The browser narrows the Paper Type list to the chosen
    category; this is the check that makes "Cabin Crew + Paper 1" impossible
    for a submission that never went through that dropdown.

    Paper Type accepts every configured paper so that an out-of-category value
    reaches the combination check and is refused with an explanation, rather
    than being rejected as "not one of the available choices".

    The markup lives in partials/exam_selection.html, which rebuilds the Paper
    Type list from the catalogue as the category changes. The fields here
    supply the choices and, more importantly, the check.
    """

    def _build_exam_selection(self):
        self.fields['exam_category'] = forms.ChoiceField(
            choices=[('', 'Select Examination Category')] + list(ExamCategory.choices),
            widget=forms.Select(attrs={'class': 'form-input'}),
            label='Examination Category',
        )
        self.fields['paper_type'] = forms.ChoiceField(
            # Read per request, so a paper added or retired in the admin takes
            # effect on the next page load.
            choices=[('', 'Select Paper Type')] + paper_types.all_choices(),
            widget=forms.Select(attrs={'class': 'form-input'}),
            label='Paper Type',
        )

    def _clean_exam_selection(self, cleaned):
        category = cleaned.get('exam_category')
        paper = cleaned.get('paper_type')
        if not category or not paper:
            return cleaned
        if not paper_types.is_valid(category, paper):
            self.add_error(
                'paper_type',
                f'{paper_types.label_for(category, paper)} is not a paper of '
                f'the {dict(ExamCategory.choices).get(category, category)} '
                'examination. Choose a paper from that category.',
            )
        return cleaned


class ExamScheduleForm(ExamSelectionMixin, forms.ModelForm):
    class Meta:
        model = ExamSchedule
        fields = [
            'candidate_name',
            'exam_number',
            'receipt_number',
            'company_name',
            'exam_category',
            'paper_type',
            'exam_date',
            'exam_time',
            'venue',
            'photo',
        ]
        widgets = {
            'candidate_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Full name as on ID',
                'autocomplete': 'off',
            }),
            'exam_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Unique exam number',
            }),
            'receipt_number': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Payment receipt number',
            }),
            'company_name': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Employer / training organization',
            }),
            'exam_date': forms.DateInput(attrs={
                'class': 'form-input',
                'type': 'date',
            }),
            'exam_time': forms.TimeInput(attrs={
                'class': 'form-input',
                'type': 'time',
            }),
            'venue': forms.TextInput(attrs={
                'class': 'form-input',
                'placeholder': 'Examination venue',
            }),
            'photo': forms.FileInput(attrs={
                'class': 'form-input',
                'accept': 'image/*',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Replace the plain model fields with the dependent pair, so the
        # manual screen offers the same narrowed Paper Type list.
        self._build_exam_selection()
        self.fields['photo'].required = False
        # The model allows a null schedule so a confirmed application can hold
        # examination IDs before a date is set. This form schedules directly,
        # so it still demands all three.
        for name in ('exam_date', 'exam_time', 'venue'):
            self.fields[name].required = True

    def clean(self):
        return self._clean_exam_selection(super().clean())

    def clean_exam_number(self):
        exam_number = self.cleaned_data['exam_number'].strip().upper()
        qs = ExamSchedule.objects.filter(exam_number__iexact=exam_number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('This exam number is already scheduled.')
        return exam_number
