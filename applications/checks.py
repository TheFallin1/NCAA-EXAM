"""Deployment checks for the OCR engine.

A missing OCR engine otherwise stays invisible until an officer uploads the
first application and the processing fails. Surfacing it from `manage.py check`
means a broken deployment is caught before anyone relies on it.
"""
from django.conf import settings
from django.core.checks import Error, Warning, register

OCR_ENGINE_MISSING = 'applications.E001'
OCR_ENGINE_FAKE_IN_PRODUCTION = 'applications.E002'


@register('ocr')
def check_ocr_engine(app_configs, **kwargs):
    from .services.ocr import OCRUnavailableError, get_engine

    engine_name = (settings.OCR_ENGINE or '').strip().lower()

    if engine_name == 'fake' and not settings.DEBUG:
        return [
            Error(
                'OCR_ENGINE is set to "fake", which returns no real text.',
                hint='Set OCR_ENGINE=tesseract for any deployment that '
                     'processes genuine documents.',
                id=OCR_ENGINE_FAKE_IN_PRODUCTION,
            )
        ]

    if engine_name != 'tesseract':
        return []

    try:
        get_engine().check_available()
    except OCRUnavailableError as exc:
        return [
            Warning(
                f'The OCR engine is not usable: {exc}',
                hint=(
                    'Install Tesseract on this host (apt-get install '
                    'tesseract-ocr tesseract-ocr-eng on Linux, or the UB '
                    'Mannheim build on Windows) and set OCR_ENGINE_PATH if the '
                    'binary is not on PATH. Application processing will fail '
                    'until this is resolved.'
                ),
                id=OCR_ENGINE_MISSING,
            )
        ]
    return []
