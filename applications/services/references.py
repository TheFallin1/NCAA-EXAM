"""Human-readable reference numbers for applications."""
from django.utils import timezone

from exams.models import NumberSequence

_MAX_ATTEMPTS = 50


def next_application_reference(year=None):
    """Issue a unique application reference such as APP-2026-00042."""
    from applications.models import Application

    year = year or timezone.localdate().year
    for _ in range(_MAX_ATTEMPTS):
        value = NumberSequence.next_value('application', year)
        candidate = f'APP-{year}-{value:05d}'
        if not Application.objects.filter(reference=candidate).exists():
            return candidate

    raise RuntimeError(
        f'Could not allocate a unique application reference for {year} '
        f'after {_MAX_ATTEMPTS} attempts.'
    )
