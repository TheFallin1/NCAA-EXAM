"""Server-side identifier generation for examinations."""
from django.conf import settings
from django.utils import timezone

from .models import ExamSchedule, ExamType, NumberSequence

# Short codes used inside examination IDs, e.g. NCAA/PLT/2026/00042.
_TYPE_CODES = {
    ExamType.CABIN_CREW: 'CC',
    ExamType.AME: 'AME',
    ExamType.PILOT: 'PLT',
    ExamType.FLIGHT_DISPATCH: 'FD',
}

_MAX_ATTEMPTS = 50


def exam_type_code(exam_type):
    return _TYPE_CODES.get(exam_type, 'GEN')


def generate_exam_number(exam_type, year=None):
    """Issue a unique examination ID.

    Always generated on the server from a locked database counter. The
    existence check covers examination numbers typed by hand under the old
    manual workflow, which were never drawn from this sequence.
    """
    year = year or timezone.localdate().year
    code = exam_type_code(exam_type)
    prefix = settings.EXAM_NUMBER_PREFIX

    for _ in range(_MAX_ATTEMPTS):
        value = NumberSequence.next_value(f'exam:{code}', year)
        candidate = f'{prefix}/{code}/{year}/{value:05d}'
        if not ExamSchedule.objects.filter(exam_number=candidate).exists():
            return candidate

    raise RuntimeError(
        f'Could not allocate a unique examination number for {code}/{year} '
        f'after {_MAX_ATTEMPTS} attempts.'
    )
