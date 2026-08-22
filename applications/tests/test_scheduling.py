"""Scheduling, including the Flight Dispatch two-paper structure.

Covers acceptance scenario F.
"""
from django.test import override_settings

from applications.models import Application, ProcessingStatus
from dashboard.models import ActivityLog
from exams.models import ExamPaper, ExamSchedule, Paper

from .base import (
    AME_LETTER,
    CABIN_CREW_LETTER,
    FLIGHT_DISPATCH_LETTER,
    PILOT_LETTER,
    WorkflowTestCase,
)
from .test_workflow import ReviewHelperMixin


class SingleSittingSchedulingTests(ReviewHelperMixin, WorkflowTestCase):
    """Cabin Crew, AME and Pilot keep the original single-sitting model."""

    def test_each_single_paper_type_schedules(self):
        cases = [
            ('pilot', PILOT_LETTER),
            ('cabin_crew', CABIN_CREW_LETTER),
            ('ame', AME_LETTER),
        ]
        for index, (exam_type, letter) in enumerate(cases):
            with self.subTest(exam_type=exam_type):
                self.set_ocr_text(letter=letter, receipt=self.receipt_text)
                self.submit_application(exam_type=exam_type)
                application = Application.objects.order_by('-created_at').first()
                self.post_review(
                    application, receipt_number=f'NCAA/2026/0050{index:02d}'
                )

                response = self.client.post(
                    f'/applications/{application.pk}/schedule/', self.schedule_data()
                )
                self.assertEqual(response.status_code, 302)

                application.refresh_from_db()
                self.assertEqual(
                    application.processing_status, ProcessingStatus.SCHEDULED
                )
                for exam in application.exam_records.all():
                    self.assertEqual(str(exam.exam_date), '2027-03-15')
                    self.assertEqual(exam.papers.count(), 0)

    def test_a_past_date_is_refused(self):
        self.submit_application(exam_type='pilot')
        application = Application.objects.get()
        self.post_review(application)

        response = self.client.post(
            f'/applications/{application.pk}/schedule/',
            {'exam_date': '2020-01-01', 'exam_time': '09:00', 'venue': 'Hall A'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'exam_date',
            'The examination date cannot be in the past.',
        )
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.CONFIRMED)

    def test_scheduling_before_confirmation_is_not_reachable(self):
        self.submit_application(exam_type='pilot')
        application = Application.objects.get()
        response = self.client.get(f'/applications/{application.pk}/schedule/')
        self.assertEqual(response.status_code, 404)


class FlightDispatchTests(ReviewHelperMixin, WorkflowTestCase):
    """Scenario F: Flight Dispatch carries Paper 1 and Paper 2."""

    letter_text = FLIGHT_DISPATCH_LETTER

    def confirmed_application(self):
        self.submit_application(exam_type='flight_dispatch')
        application = Application.objects.get()
        self.post_review(application)
        application.refresh_from_db()
        return application

    def test_confirmation_creates_both_papers_per_candidate(self):
        application = self.confirmed_application()
        self.assertEqual(application.exam_records.count(), 2)

        for exam in application.exam_records.all():
            papers = list(exam.papers.order_by('paper'))
            self.assertEqual(len(papers), 2)
            self.assertEqual(
                [p.paper for p in papers], [Paper.PAPER_1, Paper.PAPER_2]
            )
            # Not scheduled yet.
            self.assertFalse(any(p.is_scheduled for p in papers))

    def test_papers_can_sit_on_different_days(self):
        """NCAA runs the two papers on separate days; both must persist."""
        application = self.confirmed_application()

        response = self.client.post(
            f'/applications/{application.pk}/schedule/',
            self.schedule_data(multi_paper=True, shared=False),
        )
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.SCHEDULED)

        for exam in application.exam_records.all():
            paper_1 = exam.papers.get(paper=Paper.PAPER_1)
            paper_2 = exam.papers.get(paper=Paper.PAPER_2)

            self.assertEqual(str(paper_1.exam_date), '2027-03-15')
            self.assertEqual(str(paper_1.exam_time), '09:00:00')
            self.assertEqual(paper_1.venue, 'NCAA HQ, Abuja - Hall A')

            self.assertEqual(str(paper_2.exam_date), '2027-03-17')
            self.assertEqual(str(paper_2.exam_time), '13:30:00')
            self.assertEqual(paper_2.venue, 'NCAA HQ, Abuja - Hall B')

            self.assertNotEqual(paper_1.exam_date, paper_2.exam_date)

    def test_papers_can_share_one_sitting(self):
        """The other configuration must work too, without code changes."""
        application = self.confirmed_application()

        self.client.post(
            f'/applications/{application.pk}/schedule/',
            self.schedule_data(multi_paper=True, shared=True),
        )

        for exam in application.exam_records.all():
            paper_1 = exam.papers.get(paper=Paper.PAPER_1)
            paper_2 = exam.papers.get(paper=Paper.PAPER_2)
            self.assertEqual(paper_1.exam_date, paper_2.exam_date)
            self.assertEqual(paper_1.exam_time, paper_2.exam_time)
            self.assertEqual(paper_1.venue, paper_2.venue)

    def test_parent_record_mirrors_paper_one(self):
        """Keeps the dashboard, calendar and record list working unchanged."""
        application = self.confirmed_application()
        self.client.post(
            f'/applications/{application.pk}/schedule/',
            self.schedule_data(multi_paper=True, shared=False),
        )

        for exam in application.exam_records.all():
            paper_1 = exam.papers.get(paper=Paper.PAPER_1)
            self.assertEqual(exam.exam_date, paper_1.exam_date)
            self.assertEqual(exam.exam_time, paper_1.exam_time)
            self.assertEqual(exam.venue, paper_1.venue)
            self.assertEqual(exam.status, ExamSchedule.Status.SCHEDULED)

    def test_paper_two_is_required_when_not_shared(self):
        application = self.confirmed_application()
        response = self.client.post(
            f'/applications/{application.pk}/schedule/',
            {
                'paper_1_exam_date': '2027-03-15',
                'paper_1_exam_time': '09:00',
                'paper_1_venue': 'Hall A',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'paper_2_exam_date',
            'Enter the Paper 2 date, or tick the shared-schedule box.',
        )

    def test_a_past_paper_two_date_is_refused(self):
        application = self.confirmed_application()
        response = self.client.post(
            f'/applications/{application.pk}/schedule/',
            {
                'paper_1_exam_date': '2027-03-15',
                'paper_1_exam_time': '09:00',
                'paper_1_venue': 'Hall A',
                'paper_2_exam_date': '2020-01-01',
                'paper_2_exam_time': '09:00',
                'paper_2_venue': 'Hall B',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'paper_2_exam_date',
            'The examination date cannot be in the past.',
        )

    @override_settings(FLIGHT_DISPATCH_SHARED_SCHEDULE_DEFAULT=False)
    def test_separate_schedules_are_the_default(self):
        """NCAA sits the papers on different days, so the box starts clear."""
        application = self.confirmed_application()
        response = self.client.get(f'/applications/{application.pk}/schedule/')
        self.assertFalse(response.context['form'].fields['share_schedule'].initial)

    @override_settings(FLIGHT_DISPATCH_SHARED_SCHEDULE_DEFAULT=True)
    def test_shared_default_is_configurable(self):
        application = self.confirmed_application()
        response = self.client.get(f'/applications/{application.pk}/schedule/')
        self.assertTrue(response.context['form'].fields['share_schedule'].initial)

    def test_only_flight_dispatch_gets_papers(self):
        self.set_ocr_text(letter=PILOT_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_type='pilot')
        application = Application.objects.order_by('-created_at').first()
        self.post_review(application)

        self.assertFalse(
            ExamPaper.objects.filter(exam__application=application).exists()
        )

    def test_each_paper_is_audited(self):
        application = self.confirmed_application()
        self.client.post(
            f'/applications/{application.pk}/schedule/',
            self.schedule_data(multi_paper=True, shared=False),
        )

        entries = ActivityLog.objects.filter(
            action=ActivityLog.Action.PAPER_SCHEDULED
        )
        # Two candidates, two papers each.
        self.assertEqual(entries.count(), 4)
        descriptions = ' '.join(entries.values_list('description', flat=True))
        self.assertIn('Paper 1', descriptions)
        self.assertIn('Paper 2', descriptions)
