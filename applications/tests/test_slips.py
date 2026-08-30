"""Examination slip generation, for both single-sitting and Flight Dispatch."""
from applications.models import Application
from exams.models import Paper
from slips.models import SlipRecord
from slips.utils import render_slip_pdf, render_slips_pdf

from .base import FLIGHT_DISPATCH_LETTER, WorkflowTestCase
from .test_workflow import ReviewHelperMixin


class SlipContentTests(ReviewHelperMixin, WorkflowTestCase):
    def scheduled_application(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)
        self.client.post(
            f'/applications/{application.pk}/schedule/', self.schedule_data()
        )
        application.refresh_from_db()
        return application

    def test_a_slip_shows_the_candidate_details(self):
        application = self.scheduled_application()
        exam = application.exam_records.get(candidate_name='JOHN ADEWALE')

        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'JOHN ADEWALE')
        self.assertContains(response, exam.exam_number)
        self.assertContains(response, 'NCAA/2026/004821')
        self.assertContains(response, 'Pilot')
        self.assertContains(response, 'NCAA HQ, Abuja - Hall A')

    def test_one_slip_exists_for_every_candidate(self):
        application = self.scheduled_application()
        response = self.client.get(f'/slips/application/{application.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['slips']), 5)

        for exam in application.exam_records.all():
            self.assertContains(response, exam.candidate_name)
            self.assertContains(response, exam.exam_number)

    def test_viewing_a_slip_records_it(self):
        application = self.scheduled_application()
        exam = application.exam_records.first()
        self.client.get(f'/slips/{exam.pk}/')

        record = SlipRecord.objects.get(exam=exam)
        self.assertEqual(record.preview_count, 1)

    def test_a_single_slip_pdf_is_produced(self):
        application = self.scheduled_application()
        exam = application.exam_records.first()

        response = self.client.get(f'/slips/{exam.pk}/pdf/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_the_pdf_filename_is_safe_despite_slashes_in_the_id(self):
        """Examination IDs contain '/', which must not reach the header."""
        application = self.scheduled_application()
        exam = application.exam_records.first()

        response = self.client.get(f'/slips/{exam.pk}/pdf/')
        disposition = response['Content-Disposition']
        self.assertNotIn('/', disposition.split('filename=')[1])

    def test_all_slips_download_as_one_pdf(self):
        application = self.scheduled_application()
        response = self.client.get(f'/slips/application/{application.pk}/pdf/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_downloading_the_batch_records_every_slip(self):
        application = self.scheduled_application()
        self.client.get(f'/slips/application/{application.pk}/pdf/')

        records = SlipRecord.objects.filter(exam__application=application)
        self.assertEqual(records.count(), 5)
        for record in records:
            self.assertEqual(record.pdf_download_count, 1)

    def test_slips_require_authentication(self):
        application = self.scheduled_application()
        exam = application.exam_records.first()
        self.client.logout()

        for url in (
            f'/slips/{exam.pk}/',
            f'/slips/{exam.pk}/pdf/',
            f'/slips/application/{application.pk}/',
            f'/slips/application/{application.pk}/pdf/',
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/accounts/login/', response['Location'])


class PaperOnTheSlipTests(ReviewHelperMixin, WorkflowTestCase):
    """The slip must state the paper as well as the category."""

    letter_text = FLIGHT_DISPATCH_LETTER

    def scheduled_application(self, paper_type='paper_2'):
        self.submit_application(
            exam_category='flight_dispatch', paper_type=paper_type
        )
        application = Application.objects.get()
        self.post_review(application)
        self.client.post(
            f'/applications/{application.pk}/schedule/', self.schedule_data()
        )
        application.refresh_from_db()
        return application

    def test_slip_shows_the_category_and_the_paper(self):
        application = self.scheduled_application()
        exam = application.exam_records.first()

        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertContains(response, 'Flight Dispatch')
        self.assertContains(response, 'Paper 2')
        self.assertContains(response, 'Hall A')

    def test_the_paper_is_never_omitted(self):
        application = self.scheduled_application(paper_type='paper_1')
        exam = application.exam_records.first()

        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertContains(response, '>Paper<')
        self.assertContains(response, 'Paper 1')

    def test_the_batch_slip_shows_the_paper(self):
        application = self.scheduled_application()
        response = self.client.get(f'/slips/application/{application.pk}/')
        self.assertContains(response, 'Paper 2')

    def test_pdf_renders_with_the_paper(self):
        application = self.scheduled_application()
        exam = application.exam_records.first()
        self.assertTrue(render_slip_pdf(exam, request=None).startswith(b'%PDF'))

    def test_batch_pdf_renders(self):
        application = self.scheduled_application()
        pdf = render_slips_pdf(list(application.exam_records.all()), request=None)
        self.assertTrue(pdf.startswith(b'%PDF'))


class UnscheduledSlipTests(ReviewHelperMixin, WorkflowTestCase):
    def test_a_confirmed_but_unscheduled_slip_says_so(self):
        """An examination ID exists before a date does; the slip must cope."""
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)

        exam = application.exam_records.first()
        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'To be advised')

    def test_an_unscheduled_slip_still_renders_as_pdf(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)

        exam = application.exam_records.first()
        self.assertTrue(render_slip_pdf(exam, request=None).startswith(b'%PDF'))
