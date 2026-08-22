"""Process queued applications and recover interrupted ones.

Normally OCR runs in a background thread started by the upload request. If the
server restarts mid-run that thread dies, so this command exists to finish the
work. Safe to run from cron on the NCAA server.
"""
from django.core.management.base import BaseCommand

from applications.models import Application, ProcessingStatus
from applications.services.jobs import reclaim_stale, run_now


class Command(BaseCommand):
    help = 'Process queued applications and fail any whose processing stalled.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reclaim-only',
            action='store_true',
            help='Only mark stalled applications as failed; process nothing.',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=None,
            help='Seconds before an in-flight application counts as stalled.',
        )

    def handle(self, *args, **options):
        reclaimed = reclaim_stale(options['timeout'])
        if reclaimed:
            self.stdout.write(
                self.style.WARNING(f'Marked {reclaimed} stalled application(s) as failed.')
            )

        if options['reclaim_only']:
            return

        queued = list(
            Application.objects.filter(
                processing_status=ProcessingStatus.QUEUED
            ).values_list('pk', flat=True)
        )
        for application_id in queued:
            self.stdout.write(f'Processing {application_id}...')
            run_now(application_id)

        self.stdout.write(
            self.style.SUCCESS(f'Processed {len(queued)} queued application(s).')
        )
