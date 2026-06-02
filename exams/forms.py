from django import forms
from django.core.exceptions import ValidationError

from .models import ExamSchedule, ExamType


class ExamScheduleForm(forms.ModelForm):
    class Meta:
        model = ExamSchedule
        fields = [
            'candidate_name',
            'exam_number',
            'receipt_number',
            'company_name',
            'exam_type',
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
            'exam_type': forms.Select(attrs={'class': 'form-input'}),
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
        self.fields['exam_type'].choices = [('', 'Select exam type')] + list(ExamType.choices)
        self.fields['photo'].required = False

    def clean_exam_number(self):
        exam_number = self.cleaned_data['exam_number'].strip().upper()
        qs = ExamSchedule.objects.filter(exam_number__iexact=exam_number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError('This exam number is already scheduled.')
        return exam_number
