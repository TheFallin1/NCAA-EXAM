from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError

from accounts.models import OfficerProfile


class Command(BaseCommand):
    help = 'Create an examination officer account with profile and group membership.'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str)
        parser.add_argument('--password', type=str, required=True)
        parser.add_argument('--email', type=str, default='')
        parser.add_argument('--first-name', type=str, default='')
        parser.add_argument('--last-name', type=str, default='')
        parser.add_argument('--employee-id', type=str, default='')
        parser.add_argument('--phone', type=str, default='')
        parser.add_argument(
            '--admin',
            action='store_true',
            help='Also assign System Admin group',
        )

    def handle(self, *args, **options):
        username = options['username']
        if User.objects.filter(username=username).exists():
            raise CommandError(f'User "{username}" already exists.')

        user = User.objects.create_user(
            username=username,
            password=options['password'],
            email=options['email'],
            first_name=options['first_name'],
            last_name=options['last_name'],
        )
        OfficerProfile.objects.create(
            user=user,
            employee_id=options['employee_id'],
            phone=options['phone'],
        )

        officer_group, _ = Group.objects.get_or_create(
            name=settings.GROUP_EXAMINATION_OFFICER
        )
        user.groups.add(officer_group)

        if options['admin']:
            admin_group, _ = Group.objects.get_or_create(name=settings.GROUP_SYSTEM_ADMIN)
            user.groups.add(admin_group)
            user.is_staff = True
            user.save(update_fields=['is_staff'])

        self.stdout.write(self.style.SUCCESS(f'Officer "{username}" created successfully.'))
