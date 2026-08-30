"""Applications that arrive without a letterhead.

Not every application comes on an organisation's paper. A candidate applying
for themselves has no company to name, and a blank company on an examination
slip reads as a missing value rather than as the fact it is -- so it is
recorded and printed as PRIVATE.
"""
from datetime import date, time, timedelta

from exams.models import PRIVATE_APPLICANT, ExamSchedule
from slips.utils import render_slip_pdf

from .base import PILOT_LETTER, PRIVATE_APPLICANT_LETTER, WorkflowTestCase, create_officer
from .test_workflow import ReviewHelperMixin


class ExtractionTests(WorkflowTestCase):
    letter_text = PRIVATE_APPLICANT_LETTER

    def test_a_letter_without_a_letterhead_reads_as_private(self):
        self.submit_application(exam_category='pilot')
        application = self.applications().get()
        self.assertEqual(application.company_name, PRIVATE_APPLICANT)

    def test_a_letterhead_is_still_read_when_there_is_one(self):
        """The rule must not swallow a company that is actually stated."""
        self.set_ocr_text(letter=PILOT_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')
        application = self.applications().order_by('-created_at').first()
        self.assertNotEqual(application.company_name, PRIVATE_APPLICANT)
        self.assertIn('SKYWAY', application.company_name.upper())

    def applications(self):
        from applications.models import Application

        return Application.objects


class RecordAndSlipTests(ReviewHelperMixin, WorkflowTestCase):
    letter_text = PRIVATE_APPLICANT_LETTER

    def confirmed_exam(self, company_name=None):
        self.submit_application(exam_category='pilot')
        from applications.models import Application

        application = Application.objects.get()
        extra = {} if company_name is None else {'company_name': company_name}
        self.post_review(application, extra_fields=extra)
        return application.exam_records.get()

    def test_the_examination_record_carries_private(self):
        exam = self.confirmed_exam()
        self.assertEqual(exam.company_name, PRIVATE_APPLICANT)

    def test_an_officer_who_clears_the_box_still_gets_private(self):
        exam = self.confirmed_exam(company_name='')
        self.assertEqual(exam.company_name, PRIVATE_APPLICANT)

    def test_an_officer_can_still_name_a_company(self):
        exam = self.confirmed_exam(company_name='Arik Air Training')
        self.assertEqual(exam.company_name, 'Arik Air Training')

    def test_the_slip_prints_private(self):
        exam = self.confirmed_exam()
        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertContains(response, PRIVATE_APPLICANT)

    def test_the_slip_pdf_renders(self):
        exam = self.confirmed_exam()
        self.assertTrue(render_slip_pdf(exam, request=None).startswith(b'%PDF'))


class LegacyRecordTests(WorkflowTestCase):
    """Records written before this rule can hold a blank company."""

    def test_a_blank_company_displays_as_private(self):
        officer = create_officer(username='legacy-officer')
        exam = ExamSchedule.objects.create(
            candidate_name='Legacy Candidate',
            exam_number='NCAA/PLT/2026/09999',
            receipt_number='RCP-LEGACY',
            company_name='',
            exam_category='pilot',
            exam_date=date.today() + timedelta(days=30),
            exam_time=time(9, 0),
            venue='Hall A',
            scheduled_by=officer,
        )
        self.assertEqual(exam.company_display, PRIVATE_APPLICANT)

        response = self.client.get(f'/slips/{exam.pk}/')
        self.assertContains(response, PRIVATE_APPLICANT)
