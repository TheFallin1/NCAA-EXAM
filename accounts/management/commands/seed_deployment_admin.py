from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import OfficerProfile


class Command(BaseCommand):
    help = 'Seed deployment admin account from environment variables.'

    def handle(self, *args, **options):
        username = settings.env('DEPLOYMENT_ADMIN_USERNAME', default='')
        password = settings.env('DEPLOYMENT_ADMIN_PASSWORD', default='')
        email = settings.env('DEPLOYMENT_ADMIN_EMAIL', default='admin@ncaa.gov.ng')
        first_name = settings.env('DEPLOYMENT_ADMIN_FIRST_NAME', default='System')
        last_name = settings.env('DEPLOYMENT_ADMIN_LAST_NAME', default='Administrator')
        employee_id = settings.env('DEPLOYMENT_ADMIN_EMPLOYEE_ID', default='NCAA-AD-DEPLOY')
        phone = settings.env('DEPLOYMENT_ADMIN_PHONE', default='')

        if not username or not password:
            raise CommandError(
                'DEPLOYMENT_ADMIN_USERNAME and DEPLOYMENT_ADMIN_PASSWORD environment variables are required.'
            )

        with transaction.atomic():
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'is_staff': True,
                    'is_superuser': True,
                    'is_active': True,
                },
            )

            if not created:
                user.set_password(password)
                user.is_staff = True
                user.is_superuser = True
                user.is_active = True
                user.email = email
                user.first_name = first_name
                user.last_name = last_name
                user.save()
            else:
                user.set_password(password)
                user.save()

            profile, _ = OfficerProfile.objects.get_or_create(user=user)
            profile.employee_id = employee_id
            profile.phone = phone
            profile.is_active_officer = True
            profile.save()

            admin_group, _ = Group.objects.get_or_create(name=settings.GROUP_SYSTEM_ADMIN)
            officer_group, _ = Group.objects.get_or_create(name=settings.GROUP_EXAMINATION_OFFICER)
            user.groups.add(admin_group, officer_group)

        action = 'Created' if created else 'Updated'
        self.stdout.write(
            self.style.SUCCESS(f'{action} deployment admin: {username}')
        )
