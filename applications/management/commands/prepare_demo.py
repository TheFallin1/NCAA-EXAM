"""Get the machine ready for a demonstration in one step.

Applies migrations, creates the demo accounts, generates the sample scans, and
reports whether the OCR engine is actually usable, so problems surface now
rather than in front of an audience.
"""
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Prepare demo accounts, sample documents and verify the OCR engine.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--skip-documents',
            action='store_true',
            help='Do not regenerate the sample scans.',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Applying migrations'))
        call_command('migrate', verbosity=0)

        self.stdout.write(self.style.MIGRATE_HEADING('Creating demo accounts'))
        call_command('seed_demo_data', verbosity=0)

        if not options['skip_documents']:
            self.stdout.write(self.style.MIGRATE_HEADING('Generating sample documents'))
            call_command('generate_demo_documents', verbosity=0)

        self.stdout.write(self.style.MIGRATE_HEADING('Checking the OCR engine'))
        ocr_ready = self._check_ocr()

        self._summary(ocr_ready)

    def _check_ocr(self):
        from applications.services.ocr import OCRUnavailableError, get_engine

        try:
            engine = get_engine()
            engine.check_available()
        except OCRUnavailableError as exc:
            self.stdout.write(self.style.ERROR(f'  OCR NOT READY: {exc}'))
            self.stdout.write(
                '  Install Tesseract and set OCR_ENGINE_PATH in .env, then '
                'run this command again.'
            )
            return False

        if engine.name == 'fake':
            self.stdout.write(self.style.WARNING(
                '  OCR_ENGINE is "fake" - no real text will be read. '
                'Set OCR_ENGINE=tesseract in .env.'
            ))
            return False

        import pytesseract

        self.stdout.write(self.style.SUCCESS(
            f'  Tesseract {pytesseract.get_tesseract_version()} ready.'
        ))
        return True

    def _summary(self, ocr_ready):
        documents = Path('demo_documents')
        write = self.stdout.write

        write('')
        write('=' * 66)
        write(' NCAA Examination Scheduling - ready to demonstrate')
        write('=' * 66)
        write('')
        write('  URL       http://127.0.0.1:8000/accounts/login/')
        write('')
        write('  Officer   username: officer   password: Officer@2025')
        write('  Admin     username: admin     password: Admin@2025')
        write('             (admin also reaches the portal at /system/)')
        write('')

        if documents.exists():
            write(f'  Sample documents: {documents.resolve()}')
            write('    scans/    page images -> real OCR (use these to demo)')
            write('    digital/  PDFs with a text layer -> read instantly')
            write(f'    See {documents / "README.txt"} for what to select per file.')
            write('')

        write('  Suggested run-through:')
        write('    1. Sign in as officer, choose "Process Application".')
        write('    2. Select "Pilot", upload scans/01_pilot_letter.png and')
        write('       scans/01_pilot_receipt.png. Note the button stays')
        write('       disabled until both documents are provided.')
        write('    3. Watch OCR run, then verify the 5 candidates, correct a')
        write('       name, and confirm. Five examination IDs are issued.')
        write('    4. Schedule it, then print the slips.')
        write('    5. Repeat with 02_flight_dispatch to show Paper 1 / Paper 2.')
        write('    6. Repeat with 05_mismatch, selecting "Pilot", to show')
        write('       processing being blocked on an examination-type mismatch.')
        write('')

        if not ocr_ready:
            write(self.style.ERROR(
                '  WARNING: OCR is not ready. Application processing will fail.'
            ))
            write('')

        write(f'  OCR engine: {settings.OCR_ENGINE}')
        write(f'  Documents stored in: {settings.PRIVATE_MEDIA_ROOT}')
        write('=' * 66)
