"""End-to-end workflow: verification, confirmation, examination IDs.

Covers acceptance scenarios A, D, E and F. Scenarios B and C (missing
documents) live in test_documents.py alongside the rest of the upload rules.
"""
from django.contrib.auth.models import User

from applications.models import Application, ExtractedCandidate, ProcessingStatus
from applications.services.confirmation import ConfirmationError, confirm
from dashboard.models import ActivityLog
from exams.models import ExamSchedule

from .base import (
    AME_LETTER,
    CABIN_CREW_LETTER,
    FLIGHT_DISPATCH_LETTER,
    PILOT_LETTER,
    WorkflowTestCase,
    create_officer,
)


class ReviewHelperMixin:
    def review_data(self, application, names=None, receipt_number=None,
                    action='confirm', include=None, added=None, extra_fields=None):
        """Build the POST body the verification screen would submit."""
        candidates = list(application.extracted_candidates.order_by('position'))
        blanks = 2
        data = {
            'form-TOTAL_FORMS': str(len(candidates) + blanks),
            'form-INITIAL_FORMS': str(len(candidates)),
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
            'receipt_number': (
                receipt_number if receipt_number is not None
                else application.receipt_number
            ),
            'company_name': application.company_name,
            'action': action,
        }
        for index, candidate in enumerate(candidates):
            data[f'form-{index}-id'] = str(candidate.pk)
            data[f'form-{index}-corrected_name'] = (
                names[index] if names else candidate.name
            )
            if include is None or include[index]:
                data[f'form-{index}-is_included'] = 'on'

        for offset in range(blanks):
            index = len(candidates) + offset
            data[f'form-{index}-id'] = ''
            value = ''
            if added and offset < len(added):
                value = added[offset]
                data[f'form-{index}-is_included'] = 'on'
            data[f'form-{index}-corrected_name'] = value

        data.update(extra_fields or {})
        return data

    def post_review(self, application, **kwargs):
        return self.client.post(
            f'/applications/{application.pk}/review/',
            self.review_data(application, **kwargs),
        )

    def schedule_data(self):
        """The single sitting an application is scheduled for."""
        return {
            'exam_date': '2027-03-15',
            'exam_time': '09:00',
            'venue': 'NCAA HQ, Abuja - Hall A',
        }


class ScenarioAPilotTests(ReviewHelperMixin, WorkflowTestCase):
    """Scenario A: a clean five-candidate Pilot application, end to end."""

    def test_full_flow(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        # OCR extracted the type, the candidates and the receipt.
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(application.detected_exam_category, 'pilot')
        self.assertEqual(application.receipt_number, 'NCAA/2026/004821')
        self.assertEqual(application.extracted_candidates.count(), 5)

        # Nothing official exists before confirmation.
        self.assertFalse(ExamSchedule.objects.exists())

        response = self.post_review(application)
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.CONFIRMED)
        self.assertEqual(application.exam_records.count(), 5)

        response = self.client.post(
            f'/applications/{application.pk}/schedule/', self.schedule_data()
        )
        self.assertEqual(response.status_code, 302)

        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.SCHEDULED)
        for exam in application.exam_records.all():
            self.assertEqual(str(exam.exam_date), '2027-03-15')
            self.assertEqual(exam.venue, 'NCAA HQ, Abuja - Hall A')
            self.assertTrue(exam.is_scheduled)

    def test_examination_ids_are_unique_and_server_generated(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)

        numbers = list(
            application.exam_records.values_list('exam_number', flat=True)
        )
        self.assertEqual(len(numbers), 5)
        self.assertEqual(len(set(numbers)), 5)
        for number in numbers:
            self.assertTrue(number.startswith('NCAA/PLT/'))

    def test_ids_stay_unique_across_applications(self):
        numbers = set()
        # Distinct receipts: the same one twice is a duplicate and is blocked.
        for receipt in ('NCAA/2026/004821', 'NCAA/2026/004822'):
            self.submit_application(exam_category='pilot')
            application = Application.objects.order_by('-created_at').first()
            self.post_review(application, receipt_number=receipt)
            numbers.update(application.exam_records.values_list('exam_number', flat=True))
        self.assertEqual(len(numbers), 10)

    def test_records_carry_the_application_and_receipt(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)

        for exam in application.exam_records.all():
            self.assertEqual(exam.application_id, application.pk)
            self.assertEqual(exam.receipt_number, 'NCAA/2026/004821')
            self.assertEqual(exam.exam_category, 'pilot')

    def test_pending_records_are_not_scheduled_until_the_schedule_step(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)

        for exam in application.exam_records.all():
            self.assertIsNone(exam.exam_date)
            self.assertEqual(exam.status, ExamSchedule.Status.PENDING_SCHEDULE)


class ScenarioDMismatchTests(ReviewHelperMixin, WorkflowTestCase):
    """Scenario D: officer selection and letter disagree."""

    def test_mismatch_blocks_processing(self):
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.MISMATCH)
        self.assertEqual(application.exam_category, 'pilot')
        self.assertEqual(application.detected_exam_category, 'cabin_crew')

    def test_mismatch_creates_no_candidates_or_records(self):
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')

        self.assertFalse(ExtractedCandidate.objects.exists())
        self.assertFalse(ExamSchedule.objects.exists())

    def test_mismatch_cannot_be_confirmed_through(self):
        """The officer must not be able to push past the block."""
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        self.post_review(application)
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.MISMATCH)
        self.assertFalse(ExamSchedule.objects.exists())

    def test_confirm_service_refuses_a_blocked_application(self):
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        with self.assertRaises(ConfirmationError):
            confirm(application)

    def test_mismatch_is_shown_with_both_values(self):
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        response = self.client.get(f'/applications/{application.pk}/review/')
        self.assertContains(response, 'Examination Category Mismatch')
        self.assertContains(response, 'Pilot')
        self.assertContains(response, 'Cabin Crew')

    def test_mismatch_is_audited(self):
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')

        self.assertTrue(
            ActivityLog.objects.filter(
                action=ActivityLog.Action.EXAM_CATEGORY_MISMATCH
            ).exists()
        )

    def test_undetectable_type_also_blocks(self):
        self.set_ocr_text(
            letter='Dear Sir,\nPlease find our payment attached.\n1. JOHN ADEWALE',
            receipt=self.receipt_text,
        )
        self.submit_application(exam_category='pilot')

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.MISMATCH)
        self.assertEqual(application.detected_exam_category, '')

    def test_matching_types_are_accepted_for_every_category(self):
        cases = [
            ('pilot', PILOT_LETTER),
            ('cabin_crew', CABIN_CREW_LETTER),
            ('ame', AME_LETTER),
            ('flight_dispatch', FLIGHT_DISPATCH_LETTER),
        ]
        for exam_category, letter in cases:
            with self.subTest(exam_category=exam_category):
                Application.objects.all().delete()
                self.set_ocr_text(letter=letter, receipt=self.receipt_text)
                self.submit_application(exam_category=exam_category)
                application = Application.objects.get()
                self.assertEqual(
                    application.processing_status, ProcessingStatus.REVIEW
                )
                self.assertEqual(application.detected_exam_category, exam_category)


class ScenarioEMultipleCandidateTests(ReviewHelperMixin, WorkflowTestCase):
    """Scenario E: one application, many candidates, one receipt."""

    def test_five_candidates_yield_five_records_on_one_application(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)

        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(application.exam_records.count(), 5)
        self.assertEqual(
            ExamSchedule.objects.filter(application=application).count(), 5
        )

    def test_each_candidate_keeps_its_own_name(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)

        names = set(application.exam_records.values_list('candidate_name', flat=True))
        self.assertEqual(
            names,
            {
                'JOHN ADEWALE', 'DAVID OKORO', 'MICHAEL IBRAHIM',
                'PETER WILLIAMS', 'SAMUEL ADEYEMI',
            },
        )


class OfficerCorrectionTests(ReviewHelperMixin, WorkflowTestCase):
    def test_officer_can_correct_a_misread_name(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        names = ['JOHN ADEWALE', 'DAVID OKORO', 'MICHAEL IBRAHIM',
                 'PETER WILLIAMS', 'SAMUEL ADEYEMI']
        names[3] = 'PETER WILLIAM'
        self.post_review(application, names=names)

        self.assertTrue(
            application.exam_records.filter(candidate_name='PETER WILLIAM').exists()
        )
        self.assertFalse(
            application.exam_records.filter(candidate_name='PETER WILLIAMS').exists()
        )

    def test_officer_can_exclude_a_row(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        self.post_review(application, include=[True, True, True, True, False])
        self.assertEqual(application.exam_records.count(), 4)

    def test_officer_can_add_a_candidate_ocr_missed(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        self.post_review(application, added=['FUNKE OLADELE'])
        self.assertEqual(application.exam_records.count(), 6)
        self.assertTrue(
            application.exam_records.filter(candidate_name='FUNKE OLADELE').exists()
        )

    def test_officer_can_correct_the_receipt_number(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        self.post_review(application, receipt_number='NCAA/2026/009999')
        application.refresh_from_db()
        self.assertEqual(application.receipt_number, 'NCAA/2026/009999')
        for exam in application.exam_records.all():
            self.assertEqual(exam.receipt_number, 'NCAA/2026/009999')

    def test_corrections_are_audited_with_before_and_after(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        names = ['JOHN ADEWALE', 'DAVID OKORO', 'MICHAEL IBRAHIM',
                 'PETER WILLIAM', 'SAMUEL ADEYEMI']
        self.post_review(application, names=names, action='save')

        entry = ActivityLog.objects.filter(
            action=ActivityLog.Action.OCR_EDITED
        ).first()
        self.assertIsNotNone(entry)
        changes = entry.metadata['changes']
        self.assertTrue(
            any(c.get('from') == 'PETER WILLIAMS' and c.get('to') == 'PETER WILLIAM'
                for c in changes)
        )

    def test_saving_corrections_does_not_confirm(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        self.post_review(application, action='save')
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertFalse(ExamSchedule.objects.exists())


class ConfirmationGuardTests(ReviewHelperMixin, WorkflowTestCase):
    def test_missing_receipt_number_blocks_confirmation(self):
        self.set_ocr_text(letter=PILOT_LETTER, receipt='PAYMENT RECEIPT\nPaid in full')
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.assertEqual(application.receipt_number, '')

        self.post_review(application, receipt_number='')
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertFalse(ExamSchedule.objects.exists())

    def test_all_candidates_excluded_blocks_confirmation(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        self.post_review(application, include=[False] * 5)
        application.refresh_from_db()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertFalse(ExamSchedule.objects.exists())

    def test_duplicate_receipt_blocks_confirmation(self):
        self.submit_application(exam_category='pilot')
        first = Application.objects.get()
        self.post_review(first)

        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew')
        second = Application.objects.exclude(pk=first.pk).get()

        self.post_review(second)
        second.refresh_from_db()
        self.assertEqual(second.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(second.exam_records.count(), 0)

    def test_duplicate_receipt_can_be_overridden_deliberately(self):
        self.submit_application(exam_category='pilot')
        first = Application.objects.get()
        self.post_review(first)

        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew')
        second = Application.objects.exclude(pk=first.pk).get()

        self.post_review(
            second, extra_fields={'confirm_duplicate_receipt': 'on'}
        )
        second.refresh_from_db()
        self.assertEqual(second.processing_status, ProcessingStatus.CONFIRMED)
        self.assertEqual(second.exam_records.count(), 2)

    def test_confirming_twice_is_refused(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)
        application.refresh_from_db()

        with self.assertRaises(ConfirmationError):
            confirm(application)
        self.assertEqual(application.exam_records.count(), 5)


class DuplicateCandidateTests(ReviewHelperMixin, WorkflowTestCase):
    def test_existing_candidate_is_flagged_as_a_possible_duplicate(self):
        self.submit_application(exam_category='pilot')
        first = Application.objects.get()
        self.post_review(first)

        self.set_ocr_text(letter=PILOT_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')
        second = Application.objects.exclude(pk=first.pk).get()

        flagged = second.extracted_candidates.filter(
            possible_duplicate_of__isnull=False
        )
        self.assertEqual(flagged.count(), 5)

    def test_a_duplicate_warning_does_not_block(self):
        """Warn, but let the officer decide -- retakes are legitimate."""
        self.submit_application(exam_category='pilot')
        first = Application.objects.get()
        self.post_review(first)

        self.set_ocr_text(letter=PILOT_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot')
        second = Application.objects.exclude(pk=first.pk).get()

        self.post_review(
            second,
            receipt_number='NCAA/2026/005000',
        )
        second.refresh_from_db()
        self.assertEqual(second.processing_status, ProcessingStatus.CONFIRMED)


class AuthorisationTests(ReviewHelperMixin, WorkflowTestCase):
    def test_anonymous_users_are_redirected_to_login(self):
        self.client.logout()
        for url in ('/applications/process/', '/applications/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/accounts/login/', response['Location'])

    def test_a_user_outside_the_officer_groups_is_refused(self):
        User.objects.create_user(username='outsider', password='testpass123')
        self.client.logout()
        self.client.login(username='outsider', password='testpass123')

        response = self.client.get('/applications/process/')
        self.assertEqual(response.status_code, 403)

    def test_a_second_officer_may_continue_the_work(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        colleague = create_officer(username='officer2')
        self.client.force_login(colleague)
        response = self.client.get(f'/applications/{application.pk}/review/')
        self.assertEqual(response.status_code, 200)


class AuditTrailTests(ReviewHelperMixin, WorkflowTestCase):
    def test_the_workflow_is_recorded_end_to_end(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()
        self.post_review(application)
        self.client.post(
            f'/applications/{application.pk}/schedule/', self.schedule_data()
        )

        actions = set(ActivityLog.objects.values_list('action', flat=True))
        for expected in (
            ActivityLog.Action.APPLICATION_STARTED,
            ActivityLog.Action.DOCUMENT_UPLOADED,
            ActivityLog.Action.OCR_COMPLETED,
            ActivityLog.Action.CONFIRMED,
            ActivityLog.Action.EXAM_ID_GENERATED,
            ActivityLog.Action.SCHEDULED,
        ):
            with self.subTest(action=expected):
                self.assertIn(expected, actions)

    def test_entries_identify_the_officer(self):
        self.submit_application(exam_category='pilot')
        entry = ActivityLog.objects.filter(
            action=ActivityLog.Action.APPLICATION_STARTED
        ).first()
        self.assertEqual(entry.user, self.officer)
        self.assertIsNotNone(entry.timestamp)

    def test_login_is_recorded(self):
        self.client.logout()
        self.client.login(username='officer', password='testpass123')
        self.assertTrue(
            ActivityLog.objects.filter(action=ActivityLog.Action.LOGIN).exists()
        )


class PageRenderTests(ReviewHelperMixin, WorkflowTestCase):
    """Every screen an officer can reach must render."""

    def test_intake_and_list_pages_render(self):
        for url in ('/applications/process/', '/applications/'):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_the_intake_page_offers_every_examination_type(self):
        response = self.client.get('/applications/process/')
        for label in ('Cabin Crew', 'AME', 'Pilot', 'Flight Dispatch'):
            with self.subTest(label=label):
                self.assertContains(response, label)

    def test_the_application_list_shows_progress(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        response = self.client.get('/applications/')
        self.assertContains(response, application.reference)
        self.assertContains(response, 'Awaiting verification')

    def test_the_list_can_be_filtered_by_status(self):
        self.submit_application(exam_category='pilot')
        response = self.client.get('/applications/?status=review')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['applications']), 1)

        response = self.client.get('/applications/?status=scheduled')
        self.assertEqual(len(response.context['applications']), 0)

    def test_the_review_page_renders_every_state(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        response = self.client.get(f'/applications/{application.pk}/review/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'JOHN ADEWALE')
        self.assertContains(response, 'Confirm')

    def test_the_status_endpoint_reports_progress(self):
        self.submit_application(exam_category='pilot')
        application = Application.objects.get()

        response = self.client.get(f'/applications/{application.pk}/status/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload['is_processing'])
        self.assertEqual(payload['status'], 'review')

    def test_the_schedule_page_names_the_paper_being_scheduled(self):
        """One application is for one paper, so the schedule step says which."""
        from .base import FLIGHT_DISPATCH_LETTER

        self.set_ocr_text(letter=FLIGHT_DISPATCH_LETTER, receipt=self.receipt_text)
        self.submit_application(
            exam_category='flight_dispatch', paper_type='paper_2'
        )
        application = Application.objects.get()
        self.post_review(application)

        response = self.client.get(f'/applications/{application.pk}/schedule/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Flight Dispatch')
        self.assertContains(response, 'Paper 2')
        # A single sitting: no per-paper fieldsets to fill in.
        self.assertNotContains(response, 'paper_1_exam_date')

    def test_the_navigation_offers_process_application(self):
        response = self.client.get('/')
        self.assertContains(response, 'Process Application')
        # The manual screen is kept as a fallback.
        self.assertContains(response, 'Schedule Exam')

    def test_front_end_libraries_are_served_locally(self):
        """The NCAA network is isolated; no CDN may be referenced."""
        response = self.client.get('/')
        body = response.content.decode()
        self.assertNotIn('cdn.tailwindcss.com', body)
        self.assertNotIn('cdn.jsdelivr.net', body)
        self.assertIn('/static/vendor/', body)
