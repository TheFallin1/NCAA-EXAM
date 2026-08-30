"""Scheduling.

An application is for one paper of one examination category, so it carries one
schedule. Flight Dispatch Paper 1 and Paper 2 are different examinations and
are scheduled through applications of their own, which is what lets them sit on
different days -- or the same one -- with no special case in the code.

Covers acceptance scenario F.
"""
from applications.models import Application, ProcessingStatus
from exams.models import ExamPaper, ExamSchedule

from .base import (
    AME_LETTER,
    CABIN_CREW_LETTER,
    FLIGHT_DISPATCH_LETTER,
    PILOT_LETTER,
    WorkflowTestCase,
)
from .test_workflow import ReviewHelperMixin


class SchedulingTests(ReviewHelperMixin, WorkflowTestCase):
    def test_every_category_schedules(self):
        cases = [
            ('pilot', PILOT_LETTER),
            ('cabin_crew', CABIN_CREW_LETTER),
            ('ame', AME_LETTER),
            ('flight_dispatch', FLIGHT_DISPATCH_LETTER),
        ]
        for index, (exam_category, letter) in enumerate(cases):
            with self.subTest(exam_category=exam_category):
                self.set_ocr_text(letter=letter, receipt=self.receipt_text)
                self.submit_application(exam_category=exam_category)
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
                    self.assertTrue(exam.is_scheduled)

    def test_a_past_date_is_refused(self):
        self.submit_application(exam_category='pilot')
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
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        response = self.client.get(f'/applications/{application.pk}/schedule/')
        self.assertEqual(response.status_code, 404)

    def test_no_paper_rows_are_created(self):
        """The old two-papers-per-examination model is gone."""
        self.set_ocr_text(letter=FLIGHT_DISPATCH_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='flight_dispatch')
        application = Application.objects.get()
        self.post_review(application)

        self.assertFalse(
            ExamPaper.objects.filter(exam__application=application).exists()
        )


class FlightDispatchPaperTests(ReviewHelperMixin, WorkflowTestCase):
    """Scenario F: Paper 1 and Paper 2 are scheduled as separate examinations."""

    letter_text = FLIGHT_DISPATCH_LETTER

    def schedule_paper(self, paper_type, receipt_number, exam_date, venue):
        self.set_ocr_text(letter=self.letter_text, receipt=self.receipt_text)
        self.submit_application(
            exam_category='flight_dispatch', paper_type=paper_type
        )
        application = Application.objects.order_by('-created_at').first()
        self.post_review(application, receipt_number=receipt_number)
        self.client.post(
            f'/applications/{application.pk}/schedule/',
            {'exam_date': exam_date, 'exam_time': '09:00', 'venue': venue},
        )
        application.refresh_from_db()
        return application

    def test_the_two_papers_are_separate_examinations(self):
        first = self.schedule_paper(
            'paper_1', 'NCAA/2026/006001', '2027-03-15', 'Hall A'
        )
        second = self.schedule_paper(
            'paper_2', 'NCAA/2026/006002', '2027-03-17', 'Hall B'
        )

        self.assertEqual(first.paper_type, 'paper_1')
        self.assertEqual(second.paper_type, 'paper_2')

        for exam in first.exam_records.all():
            self.assertEqual(exam.paper_type, 'paper_1')
            self.assertEqual(str(exam.exam_date), '2027-03-15')
            self.assertEqual(exam.venue, 'Hall A')
        for exam in second.exam_records.all():
            self.assertEqual(exam.paper_type, 'paper_2')
            self.assertEqual(str(exam.exam_date), '2027-03-17')
            self.assertEqual(exam.venue, 'Hall B')

    def test_the_two_papers_may_also_share_one_sitting(self):
        """Nothing forces different days; the same date is simply entered."""
        first = self.schedule_paper(
            'paper_1', 'NCAA/2026/006003', '2027-04-01', 'Hall A'
        )
        second = self.schedule_paper(
            'paper_2', 'NCAA/2026/006004', '2027-04-01', 'Hall A'
        )
        self.assertEqual(
            first.exam_records.first().exam_date,
            second.exam_records.first().exam_date,
        )

    def test_records_are_distinguishable_by_paper(self):
        """Scheduling, reporting and filtering all need both halves."""
        self.schedule_paper('paper_1', 'NCAA/2026/006005', '2027-05-01', 'Hall A')
        self.schedule_paper('paper_2', 'NCAA/2026/006006', '2027-05-02', 'Hall B')

        paper_1 = ExamSchedule.objects.filter(
            exam_category='flight_dispatch', paper_type='paper_1'
        )
        paper_2 = ExamSchedule.objects.filter(
            exam_category='flight_dispatch', paper_type='paper_2'
        )
        self.assertEqual(paper_1.count(), 2)
        self.assertEqual(paper_2.count(), 2)
        self.assertFalse(set(paper_1) & set(paper_2))
