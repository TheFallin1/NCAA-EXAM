from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import OfficerProfile
from exams.models import ExamSchedule, ExamType


class Command(BaseCommand):
    help = 'Seed demo officers and sample examination schedules for development.'

    def handle(self, *args, **options):
        officer_group, _ = Group.objects.get_or_create(
            name=settings.GROUP_EXAMINATION_OFFICER
        )
        admin_group, _ = Group.objects.get_or_create(name=settings.GROUP_SYSTEM_ADMIN)

        accounts = [
            {
                'username': 'officer',
                'password': 'Officer@2025',
                'email': 'officer@ncaa.gov.ng',
                'first_name': 'Amina',
                'last_name': 'Bello',
                'employee_id': 'NCAA-EO-001',
                'phone': '+2348010000001',
                'is_admin': False,
            },
            {
                'username': 'admin',
                'password': 'Admin@2025',
                'email': 'admin@ncaa.gov.ng',
                'first_name': 'Chidi',
                'last_name': 'Okafor',
                'employee_id': 'NCAA-AD-001',
                'phone': '+2348010000002',
                'is_admin': True,
            },
        ]

        officers = []
        for data in accounts:
            user, created = User.objects.get_or_create(
                username=data['username'],
                defaults={
                    'email': data['email'],
                    'first_name': data['first_name'],
                    'last_name': data['last_name'],
                },
            )
            user.set_password(data['password'])
            user.is_active = True
            if data['is_admin']:
                user.is_staff = True
            user.save()

            profile, _ = OfficerProfile.objects.get_or_create(user=user)
            profile.employee_id = data['employee_id']
            profile.phone = data['phone']
            profile.is_active_officer = True
            profile.save()

            user.groups.add(officer_group)
            if data['is_admin']:
                user.groups.add(admin_group)

            action = 'Created' if created else 'Updated'
            self.stdout.write(f'{action} user: {user.username}')
            officers.append(user)

        primary = officers[0]
        today = timezone.localdate()

        samples = [
            {
                'candidate_name': 'Adaeze Nwosu',
                'exam_number': 'NCAA-CC-2025-001',
                'receipt_number': 'RCP-10001',
                'company_name': 'Air Peace Training Centre',
                'exam_type': ExamType.CABIN_CREW,
                'exam_date': today + timedelta(days=2),
                'exam_time': time(9, 0),
                'venue': 'NCAA HQ, Abuja — Hall A',
            },
            {
                'candidate_name': 'Ibrahim Musa',
                'exam_number': 'NCAA-AME-2025-002',
                'receipt_number': 'RCP-10002',
                'company_name': 'Dana Maintenance Services',
                'exam_type': ExamType.AME,
                'exam_date': today,
                'exam_time': time(11, 30),
                'venue': 'NCAA HQ, Abuja — Hall B',
            },
            {
                'candidate_name': 'Grace Okonkwo',
                'exam_number': 'NCAA-PLT-2025-003',
                'receipt_number': 'RCP-10003',
                'company_name': 'Ibrahim Badamasi Babangida College of Aviation',
                'exam_type': ExamType.PILOT,
                'exam_date': today + timedelta(days=5),
                'exam_time': time(14, 0),
                'venue': 'NCAA Lagos Regional Office',
            },
            {
                'candidate_name': 'Yusuf Abdullahi',
                'exam_number': 'NCAA-FD-2025-004',
                'receipt_number': 'RCP-10004',
                'company_name': 'Max Air Dispatch Unit',
                'exam_type': ExamType.FLIGHT_DISPATCH,
                'exam_date': today + timedelta(days=1),
                'exam_time': time(10, 0),
                'venue': 'NCAA HQ, Abuja — Hall C',
            },
            {
                'candidate_name': 'Fatima Garba',
                'exam_number': 'NCAA-CC-2025-005',
                'receipt_number': 'RCP-10005',
                'company_name': 'Overland Airways',
                'exam_type': ExamType.CABIN_CREW,
                'exam_date': today - timedelta(days=3),
                'exam_time': time(8, 30),
                'venue': 'NCAA Kano Regional Office',
            },
        ]

        created_exams = 0
        for row in samples:
            _, created = ExamSchedule.objects.get_or_create(
                exam_number=row['exam_number'],
                defaults={**row, 'scheduled_by': primary},
            )
            if created:
                created_exams += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nSeeded {created_exams} new examination record(s).\n'
        ))
        self.stdout.write(self.style.WARNING('=== LOGIN CREDENTIALS (development only) ===\n'))
        self.stdout.write('URL:      http://127.0.0.1:8000/accounts/login/\n')
        self.stdout.write('Officer:  username = officer   password = Officer@2025\n')
        self.stdout.write('Admin:    username = admin     password = Admin@2025\n')
        self.stdout.write('\nAdmin can access /system/ for officer management.\n')
