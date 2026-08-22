"""Examination slip generation, for both single-sitting and Flight Dispatch."""
from applications.models import Application
from exams.models import Paper
from slips.models import SlipRecord
from slips.utils import render_slip_pdf, render_slips_pdf

from .base import FLIGHT_DISPATCH_LETTER, WorkflowTestCase
from .test_workflow import ReviewHelperMixin


class SlipContentTests(ReviewHelperMixin, WorkflowTestCase):
    def scheduled_application(self):
        self.submit_application(exam_type='pilot')
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


class FlightDispatchSlipTests(ReviewHelperMixin, WorkflowTestCase):
    letter_text = FLIGHT_DISPATCH_LETTER

    def scheduled_application(self, shared=False):
        self.submit_application(exam_type='flight_dispatch')
        application = Application.objects.get()
        self.post_review(application)
        self.client.post(
            f'/applications/{application.pk}/schedule/',
            self.schedule_data(multi_paper=True, shared=shared),
        )
        application.refresh_from_db()
        return application

    def test_slip_shows_both_papers_with_their_own_schedule(self):
        application = self.scheduled_application()
        exam = application.exam_records.first()

        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertContains(response, 'Paper 1')
        self.assertContains(response, 'Paper 2')
        self.assertContains(response, 'Hall A')
        self.assertContains(response, 'Hall B')
        self.assertContains(response, 'March 15, 2027')
        self.assertContains(response, 'March 17, 2027')

    def test_slip_shows_both_papers_when_they_share_a_sitting(self):
        application = self.scheduled_application(shared=True)
        exam = application.exam_records.first()

        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertContains(response, 'Paper 1')
        self.assertContains(response, 'Paper 2')
        self.assertContains(response, 'Hall A')

    def test_flight_dispatch_pdf_renders(self):
        application = self.scheduled_application()
        exam = application.exam_records.first()
        pdf = render_slip_pdf(exam, request=None)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_flight_dispatch_batch_pdf_renders(self):
        application = self.scheduled_application()
        pdf = render_slips_pdf(list(application.exam_records.all()), request=None)
        self.assertTrue(pdf.startswith(b'%PDF'))

    def test_single_sitting_slip_has_no_paper_blocks(self):
        self.set_ocr_text(
            letter="""SKY ACADEMY
APPLICATION FOR PILOT EXAMINATION
We submit the following candidates:
1. JOHN ADEWALE
Yours faithfully,""",
            receipt=self.receipt_text,
        )
        self.submit_application(exam_type='pilot')
        application = Application.objects.order_by('-created_at').first()
        self.post_review(application, receipt_number='NCAA/2026/007777')
        self.client.post(
            f'/applications/{application.pk}/schedule/', self.schedule_data()
        )

        exam = application.exam_records.get()
        self.assertEqual(exam.papers.count(), 0)
        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertNotContains(response, 'Paper 1')


class UnscheduledSlipTests(ReviewHelperMixin, WorkflowTestCase):
    def test_a_confirmed_but_unscheduled_slip_says_so(self):
        """An examination ID exists before a date does; the slip must cope."""
        self.submit_application(exam_type='pilot')
        application = Application.objects.get()
        self.post_review(application)

        exam = application.exam_records.first()
        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'To be advised')

    def test_an_unscheduled_slip_still_renders_as_pdf(self):
        self.submit_application(exam_type='pilot')
        application = Application.objects.get()
        self.post_review(application)

        exam = application.exam_records.first()
        self.assertTrue(render_slip_pdf(exam, request=None).startswith(b'%PDF'))
