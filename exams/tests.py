"""Examination identifiers and backward compatibility of the manual workflow.

The manual scheduling screen predates application processing and is retained as
a fallback, so these tests guard against the new models breaking it.
"""
from datetime import date, time, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from applications.tests.base import create_officer
from exams.models import ExamSchedule, ExamType, NumberSequence
from exams.services import exam_type_code, generate_exam_number

FUTURE = date.today() + timedelta(days=30)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class ExamNumberTests(TestCase):
    def test_numbers_follow_the_documented_shape(self):
        number = generate_exam_number(ExamType.PILOT, year=2026)
        self.assertRegex(number, r'^NCAA/PLT/2026/\d{5}$')

    def test_each_type_has_its_own_code_and_sequence(self):
        codes = {
            ExamType.CABIN_CREW: 'CC',
            ExamType.AME: 'AME',
            ExamType.PILOT: 'PLT',
            ExamType.FLIGHT_DISPATCH: 'FD',
        }
        for exam_type, code in codes.items():
            with self.subTest(exam_type=exam_type):
                self.assertEqual(exam_type_code(exam_type), code)
                self.assertIn(f'/{code}/', generate_exam_number(exam_type, year=2026))

    def test_numbers_increment(self):
        first = generate_exam_number(ExamType.PILOT, year=2026)
        second = generate_exam_number(ExamType.PILOT, year=2026)
        self.assertNotEqual(first, second)
        self.assertEqual(int(second.rsplit('/', 1)[1]), int(first.rsplit('/', 1)[1]) + 1)

    def test_sequences_are_independent_per_type_and_year(self):
        generate_exam_number(ExamType.PILOT, year=2026)
        ame = generate_exam_number(ExamType.AME, year=2026)
        next_year = generate_exam_number(ExamType.PILOT, year=2027)
        self.assertTrue(ame.endswith('00001'))
        self.assertTrue(next_year.endswith('00001'))

    def test_a_manually_typed_number_is_never_reissued(self):
        """Legacy records were numbered by hand, outside this sequence."""
        officer = create_officer()
        ExamSchedule.objects.create(
            candidate_name='Legacy Candidate',
            exam_number='NCAA/PLT/2026/00001',
            receipt_number='RCP-1',
            company_name='Legacy Co',
            exam_type=ExamType.PILOT,
            exam_date=FUTURE,
            exam_time=time(9, 0),
            venue='Hall A',
            scheduled_by=officer,
        )
        self.assertNotEqual(
            generate_exam_number(ExamType.PILOT, year=2026), 'NCAA/PLT/2026/00001'
        )

    def test_sequence_counter_is_stored_server_side(self):
        generate_exam_number(ExamType.PILOT, year=2026)
        row = NumberSequence.objects.get(scope='exam:PLT', year=2026)
        self.assertEqual(row.last_value, 1)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class ManualSchedulingTests(TestCase):
    """The pre-existing screen must keep working exactly as before."""

    def setUp(self):
        self.officer = create_officer()
        self.client.force_login(self.officer)

    def payload(self, **overrides):
        data = {
            'candidate_name': 'Adaeze Nwosu',
            'exam_number': 'NCAA-CC-2026-777',
            'receipt_number': 'RCP-10001',
            'company_name': 'Air Peace Training Centre',
            'exam_type': ExamType.CABIN_CREW,
            'exam_date': FUTURE.isoformat(),
            'exam_time': '09:00',
            'venue': 'NCAA HQ, Abuja - Hall A',
        }
        data.update(overrides)
        return data

    def test_an_exam_can_still_be_scheduled_by_hand(self):
        response = self.client.post('/exams/schedule/', self.payload())
        self.assertEqual(response.status_code, 302)

        exam = ExamSchedule.objects.get()
        self.assertEqual(exam.candidate_name, 'Adaeze Nwosu')
        self.assertEqual(exam.status, ExamSchedule.Status.SCHEDULED)
        self.assertIsNone(exam.application)

    def test_the_schedule_fields_are_still_mandatory_here(self):
        """The model allows nulls now; this form must not."""
        response = self.client.post(
            '/exams/schedule/', self.payload(exam_date='', exam_time='', venue='')
        )
        self.assertEqual(response.status_code, 200)
        for field in ('exam_date', 'exam_time', 'venue'):
            with self.subTest(field=field):
                self.assertFormError(
                    response.context['form'], field, 'This field is required.'
                )

    def test_duplicate_exam_numbers_are_still_rejected(self):
        self.client.post('/exams/schedule/', self.payload())
        response = self.client.post(
            '/exams/schedule/', self.payload(candidate_name='Someone Else')
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'exam_number',
            'This exam number is already scheduled.',
        )

    def test_a_past_record_can_still_be_edited(self):
        """Editing history must not be blocked by the future-date rule."""
        exam = ExamSchedule.objects.create(
            candidate_name='Past Candidate',
            exam_number='NCAA-OLD-1',
            receipt_number='RCP-9',
            company_name='Old Co',
            exam_type=ExamType.PILOT,
            exam_date=date.today() - timedelta(days=30),
            exam_time=time(9, 0),
            venue='Old Hall',
            scheduled_by=self.officer,
        )
        response = self.client.post(
            f'/exams/{exam.pk}/edit/',
            self.payload(
                candidate_name='Past Candidate',
                exam_number='NCAA-OLD-1',
                exam_type=ExamType.PILOT,
                exam_date=(date.today() - timedelta(days=30)).isoformat(),
                venue='Corrected Hall',
            ),
        )
        self.assertEqual(response.status_code, 302)
        exam.refresh_from_db()
        self.assertEqual(exam.venue, 'Corrected Hall')

    def test_new_records_still_cannot_be_dated_in_the_past(self):
        response = self.client.post(
            '/exams/schedule/',
            self.payload(exam_date=(date.today() - timedelta(days=1)).isoformat()),
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'exam_date',
            'Exam date cannot be in the past.',
        )

    def test_deleting_a_record_is_audited_with_the_officer(self):
        """Regression: the old delete() override was never called."""
        from dashboard.models import ActivityLog

        self.client.post('/exams/schedule/', self.payload())
        exam = ExamSchedule.objects.get()
        self.client.post(f'/exams/{exam.pk}/delete/')

        self.assertFalse(ExamSchedule.objects.exists())
        entry = ActivityLog.objects.filter(
            action=ActivityLog.Action.DELETE
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.user, self.officer)
        self.assertIsNotNone(entry.ip_address)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class ExistingViewCompatibilityTests(TestCase):
    """Dashboard, record list and export tolerate unscheduled records."""

    def setUp(self):
        self.officer = create_officer()
        self.client.force_login(self.officer)
        ExamSchedule.objects.create(
            candidate_name='Scheduled Person',
            exam_number='NCAA/PLT/2026/00001',
            receipt_number='RCP-1',
            company_name='Co',
            exam_type=ExamType.PILOT,
            exam_date=FUTURE,
            exam_time=time(9, 0),
            venue='Hall A',
            scheduled_by=self.officer,
        )
        ExamSchedule.objects.create(
            candidate_name='Pending Person',
            exam_number='NCAA/PLT/2026/00002',
            receipt_number='RCP-2',
            company_name='Co',
            exam_type=ExamType.PILOT,
            scheduled_by=self.officer,
        )

    def test_dashboard_renders(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], 2)

    def test_record_list_renders_both_records(self):
        response = self.client.get('/exams/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Scheduled Person')
        self.assertContains(response, 'Pending Person')
        self.assertContains(response, 'Awaiting scheduling')

    def test_sorting_by_date_does_not_error_with_nulls(self):
        for sort in ('exam_date', '-exam_date', 'candidate_name'):
            with self.subTest(sort=sort):
                response = self.client.get(f'/exams/?sort={sort}')
                self.assertEqual(response.status_code, 200)

    def test_csv_export_includes_unscheduled_records(self):
        response = self.client.get('/dashboard/export/csv/', follow=True)
        if response.status_code == 404:
            response = self.client.get('/export/csv/')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Scheduled Person', body)
        self.assertIn('Pending Person', body)

    def test_stats_api_still_responds(self):
        response = self.client.get('/api/v1/stats/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['total'], 2)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
)
class CalendarParameterTests(TestCase):
    """Query-string values reach the calendar directly and must be tolerated."""

    def setUp(self):
        self.officer = create_officer()
        self.client.force_login(self.officer)

    def test_bad_calendar_parameters_do_not_crash_the_dashboard(self):
        for query in ('?year=abc', '?month=13', '?month=0', '?year=0&month=-1',
                      '?year=99999999999'):
            with self.subTest(query=query):
                response = self.client.get('/' + query)
                self.assertEqual(response.status_code, 200)

    def test_bad_calendar_parameters_do_not_crash_the_api(self):
        for query in ('?year=abc', '?month=13'):
            with self.subTest(query=query):
                response = self.client.get('/api/v1/calendar/' + query)
                self.assertEqual(response.status_code, 200)

    def test_a_valid_month_is_honoured(self):
        response = self.client.get('/?year=2027&month=3')
        self.assertEqual(response.context['calendar_year'], 2027)
        self.assertEqual(response.context['calendar_month'], 3)
