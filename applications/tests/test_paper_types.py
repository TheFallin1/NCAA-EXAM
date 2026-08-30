"""The dependent Examination Category / Paper Type selection.

Three things are covered: the catalogue behind the second dropdown, the
context-aware detection that reads a paper out of a letter, and the validation
that compares the officer's pair with what the letter says.
"""
from django.test import TestCase, override_settings

from applications.models import Application, ProcessingStatus
from dashboard.models import ActivityLog
from exams import paper_types
from exams.models import ExamCategory, PaperType

from .base import CABIN_CREW_LETTER, FLIGHT_DISPATCH_LETTER, WorkflowTestCase
from .test_workflow import ReviewHelperMixin

# Letters that do name the paper, in the wording NCAA submissions use.
CABIN_CREW_B737_LETTER = """OVERLAND AIRWAYS LIMITED

APPLICATION FOR CABIN CREW EXAMINATION

We apply to sit the B737 examination for the candidates listed below:
1. AMINA BELLO
2. GRACE NWOSU

Yours faithfully,
"""

CABIN_CREW_GENERAL_LETTER = """OVERLAND AIRWAYS LIMITED

APPLICATION FOR CABIN CREW EXAMINATION

The candidates below are presented for the General Paper:
1. AMINA BELLO
2. GRACE NWOSU

Yours faithfully,
"""

FLIGHT_DISPATCH_PAPER_2_LETTER = """MAX AIR DISPATCH UNIT

APPLICATION FOR FLIGHT DISPATCH EXAMINATION

We submit the following candidates for Paper 2:
1. TUNDE BAKARE
2. HALIMA SADIQ

Yours faithfully,
"""

# The trap from the specification: B737 appears, but only as fleet and training
# history. Nothing here says the examination is the B737 paper.
CABIN_CREW_B737_IN_PASSING_LETTER = """AEROPORT COLLEGE OF AVIATION
Approved B737 and Q400 training organisation

APPLICATION FOR CABIN CREW EXAMINATION

The candidates below completed their B737 recurrent training in June.
1. AMINA BELLO
2. GRACE NWOSU

Yours faithfully,
"""


class CatalogueTests(TestCase):
    """The papers under each category, and what may be paired with what."""

    def test_every_category_is_seeded(self):
        expected = {
            ExamCategory.CABIN_CREW: ['b737', 'general'],
            ExamCategory.PILOT: ['general'],
            ExamCategory.FLIGHT_DISPATCH: ['paper_1', 'paper_2'],
            ExamCategory.AME: ['general', 'ame_paper_2', 'ame_paper_3'],
        }
        for category, codes in expected.items():
            with self.subTest(category=category):
                self.assertEqual(
                    [code for code, _ in paper_types.choices_for(category)], codes
                )

    def test_flight_dispatch_papers_are_not_categories(self):
        """Paper 1 and Paper 2 sit under Flight Dispatch, not beside it."""
        self.assertNotIn('paper_1', dict(ExamCategory.choices))
        self.assertEqual(
            [name for _, name in paper_types.choices_for(ExamCategory.FLIGHT_DISPATCH)],
            ['Paper 1', 'Paper 2'],
        )

    def test_a_pair_from_another_category_is_invalid(self):
        self.assertTrue(paper_types.is_valid(ExamCategory.CABIN_CREW, 'b737'))
        self.assertFalse(paper_types.is_valid(ExamCategory.CABIN_CREW, 'paper_1'))
        self.assertFalse(paper_types.is_valid(ExamCategory.PILOT, 'b737'))
        self.assertTrue(paper_types.is_valid(ExamCategory.FLIGHT_DISPATCH, 'paper_1'))

    def test_the_catalogue_only_lists_a_category_own_papers(self):
        grouped = paper_types.catalogue()
        cabin_crew = [entry['value'] for entry in grouped[ExamCategory.CABIN_CREW]]
        self.assertEqual(cabin_crew, ['b737', 'general'])
        self.assertNotIn('paper_1', cabin_crew)

    def test_a_paper_can_be_renamed_without_touching_records(self):
        """What the AME placeholders exist for."""
        paper = PaperType.objects.get(exam_category=ExamCategory.AME, code='ame_paper_2')
        paper.name = 'Airframes and Systems'
        paper.save(update_fields=['name'])

        self.assertEqual(
            paper_types.label_for(ExamCategory.AME, 'ame_paper_2'),
            'Airframes and Systems',
        )
        # The stored code is untouched, so every existing record follows along.
        self.assertTrue(paper_types.is_valid(ExamCategory.AME, 'ame_paper_2'))

    def test_a_paper_can_be_added_without_a_code_change(self):
        PaperType.objects.create(
            exam_category=ExamCategory.PILOT,
            code='air_law',
            name='Air Law',
            display_order=5,
        )
        self.assertIn(
            ('air_law', 'Air Law'), paper_types.choices_for(ExamCategory.PILOT)
        )

    def test_a_retired_paper_stops_being_offered_but_keeps_its_label(self):
        paper = PaperType.objects.get(exam_category=ExamCategory.CABIN_CREW, code='b737')
        paper.is_active = False
        paper.save(update_fields=['is_active'])

        self.assertNotIn(
            'b737',
            [code for code, _ in paper_types.choices_for(ExamCategory.CABIN_CREW)],
        )
        self.assertFalse(paper_types.is_valid(ExamCategory.CABIN_CREW, 'b737'))
        # A record scheduled under it still reads correctly.
        self.assertEqual(paper_types.label_for(ExamCategory.CABIN_CREW, 'b737'), 'B737')


class DetectionTests(TestCase):
    """Detection is contextual, and never guesses."""

    def test_a_named_paper_is_detected(self):
        cases = [
            (CABIN_CREW_B737_LETTER, ExamCategory.CABIN_CREW, 'b737'),
            (CABIN_CREW_GENERAL_LETTER, ExamCategory.CABIN_CREW, 'general'),
            (FLIGHT_DISPATCH_PAPER_2_LETTER, ExamCategory.FLIGHT_DISPATCH, 'paper_2'),
        ]
        for text, category, expected in cases:
            with self.subTest(expected=expected):
                detection = paper_types.detect(text, category)
                self.assertEqual(detection.paper_type, expected)
                self.assertTrue(detection.contextual)

    def test_a_mention_outside_an_examination_context_is_not_the_paper(self):
        """A letterhead or a training history does not name the examination."""
        detection = paper_types.detect(
            CABIN_CREW_B737_IN_PASSING_LETTER, ExamCategory.CABIN_CREW
        )
        self.assertIsNone(detection.paper_type)
        self.assertFalse(detection.detected)

    def test_an_aside_about_a_type_rating_is_not_the_paper(self):
        """The wording of a real submission, which names a different exam."""
        detection = paper_types.detect(
            "REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS. We would "
            "like to schedule the students for Air - Law and Boeing 737 Classic "
            "Type rating exam in Lagos.",
            ExamCategory.CABIN_CREW,
        )
        self.assertFalse(detection.detected)

    def test_a_letter_that_says_nothing_yields_nothing(self):
        detection = paper_types.detect(CABIN_CREW_LETTER, ExamCategory.CABIN_CREW)
        self.assertFalse(detection.detected)

    def test_two_papers_named_equally_are_ambiguous_not_resolved(self):
        detection = paper_types.detect(
            'We apply for the Flight Dispatch Paper 1 and Paper 2 examinations.',
            ExamCategory.FLIGHT_DISPATCH,
        )
        self.assertIsNone(detection.paper_type)
        self.assertTrue(detection.ambiguous)

    def test_only_the_category_own_papers_are_considered(self):
        """"Paper 1" in a Cabin Crew letter is not a Cabin Crew paper."""
        detection = paper_types.detect(
            'APPLICATION FOR CABIN CREW EXAMINATION. Candidates for Paper 1.',
            ExamCategory.CABIN_CREW,
        )
        self.assertFalse(detection.detected)

    def test_spacing_variants_of_a_term_are_read(self):
        for written in ('B737', 'B-737', 'B 737', 'Boeing 737'):
            with self.subTest(written=written):
                detection = paper_types.detect(
                    f'Candidates are presented for the {written} examination.',
                    ExamCategory.CABIN_CREW,
                )
                self.assertEqual(detection.paper_type, 'b737')

    def test_detection_terms_are_configuration(self):
        """A new term added in the admin is picked up with no code change."""
        paper = PaperType.objects.get(exam_category=ExamCategory.PILOT, code='general')
        paper.detection_terms = paper.detection_terms + '\nCommon Paper'
        paper.save(update_fields=['detection_terms'])

        detection = paper_types.detect(
            'The candidates below will sit the Common Paper.', ExamCategory.PILOT
        )
        self.assertEqual(detection.paper_type, 'general')


class IntakeSelectionTests(ReviewHelperMixin, WorkflowTestCase):
    """The two dropdowns as the officer meets them."""

    def test_the_intake_page_offers_every_category(self):
        response = self.client.get('/applications/process/')
        for label in ('Cabin Crew', 'Pilot', 'Flight Dispatch', 'AME'):
            with self.subTest(label=label):
                self.assertContains(response, label)

    def test_the_paper_dropdown_starts_disabled(self):
        response = self.client.get('/applications/process/')
        body = response.content.decode()
        self.assertIn('Select Examination Category', body)
        self.assertIn('Select Examination Category First', body)
        # Disabled until a category is chosen.
        self.assertIn('x-bind:disabled="!category"', body)

    def test_the_catalogue_reaches_the_page(self):
        response = self.client.get('/applications/process/')
        catalogue = response.context['paper_catalogue']
        self.assertIn('b737', catalogue)
        self.assertIn('paper_1', catalogue)

    def test_an_invalid_combination_is_refused(self):
        """Cabin Crew + Paper 1: Paper 1 belongs to Flight Dispatch."""
        response = self.submit_application(
            exam_category='cabin_crew', paper_type='paper_1'
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())
        self.assertFormError(
            response.context['form'],
            'paper_type',
            'Paper 1 is not a paper of the Cabin Crew examination. '
            'Choose a paper from that category.',
        )

    def test_a_missing_paper_is_refused(self):
        response = self.submit_application(exam_category='cabin_crew', paper_type='')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Application.objects.exists())

    def test_a_valid_pair_is_stored_apart(self):
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')

        application = Application.objects.get()
        self.assertEqual(application.exam_category, 'cabin_crew')
        self.assertEqual(application.paper_type, 'b737')

    def test_the_pair_reaches_the_examination_records(self):
        self.set_ocr_text(letter=CABIN_CREW_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')
        application = Application.objects.get()
        self.post_review(application)

        for exam in application.exam_records.all():
            self.assertEqual(exam.exam_category, 'cabin_crew')
            self.assertEqual(exam.paper_type, 'b737')
            self.assertEqual(exam.paper_type_label, 'B737')


class PaperValidationTests(ReviewHelperMixin, WorkflowTestCase):
    """The officer's paper against the paper the letter names."""

    def test_a_matching_paper_carries_on(self):
        self.set_ocr_text(letter=CABIN_CREW_B737_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)
        self.assertEqual(application.detected_paper_type, 'b737')

    def test_a_mismatched_paper_blocks_processing(self):
        self.set_ocr_text(letter=CABIN_CREW_GENERAL_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')

        application = Application.objects.get()
        self.assertEqual(
            application.processing_status, ProcessingStatus.PAPER_MISMATCH
        )
        self.assertEqual(application.detected_paper_type, 'general')
        self.assertEqual(
            application.error_message,
            'Paper type selected by the officer does not match the paper type '
            'detected in the application.',
        )

    def test_a_paper_mismatch_still_records_the_detected_category(self):
        """The category check has already passed; its result must persist."""
        self.set_ocr_text(letter=CABIN_CREW_GENERAL_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')

        application = Application.objects.get()
        self.assertEqual(application.detected_exam_category, 'cabin_crew')
        self.assertTrue(application.detected_paper_type_evidence)

    def test_a_paper_mismatch_creates_nothing(self):
        self.set_ocr_text(letter=CABIN_CREW_GENERAL_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')
        application = Application.objects.get()

        self.assertFalse(application.extracted_candidates.exists())
        self.assertFalse(application.exam_records.exists())

    def test_a_paper_mismatch_cannot_be_confirmed_through(self):
        self.set_ocr_text(letter=CABIN_CREW_GENERAL_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')
        application = Application.objects.get()

        self.post_review(application)
        application.refresh_from_db()
        self.assertEqual(
            application.processing_status, ProcessingStatus.PAPER_MISMATCH
        )

    def test_a_paper_mismatch_is_shown_with_both_values(self):
        self.set_ocr_text(letter=CABIN_CREW_GENERAL_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')
        application = Application.objects.get()

        response = self.client.get(f'/applications/{application.pk}/review/')
        self.assertContains(response, 'Paper Type Mismatch')
        self.assertContains(response, 'B737')
        self.assertContains(response, 'General Paper')

    def test_a_paper_mismatch_is_audited(self):
        self.set_ocr_text(letter=CABIN_CREW_GENERAL_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')

        self.assertTrue(
            ActivityLog.objects.filter(
                action=ActivityLog.Action.PAPER_TYPE_MISMATCH
            ).exists()
        )

    def test_a_category_mismatch_is_reported_as_such(self):
        """The category is checked first, and says so in its own words."""
        self.set_ocr_text(letter=CABIN_CREW_B737_LETTER, receipt=self.receipt_text)
        self.submit_application(exam_category='pilot', paper_type='general')

        application = Application.objects.get()
        self.assertEqual(application.processing_status, ProcessingStatus.MISMATCH)
        self.assertEqual(
            application.error_message,
            'Examination category selected by the officer does not match the '
            'examination category detected in the application.',
        )


class UnresolvedPaperTests(ReviewHelperMixin, WorkflowTestCase):
    """A letter that names the category but not the paper."""

    letter_text = CABIN_CREW_LETTER

    def submit(self):
        self.set_ocr_text(letter=self.letter_text, receipt=self.receipt_text)
        self.submit_application(exam_category='cabin_crew', paper_type='b737')
        return Application.objects.get()

    def test_the_paper_is_not_guessed(self):
        application = self.submit()
        self.assertEqual(application.detected_exam_category, 'cabin_crew')
        self.assertEqual(application.detected_paper_type, '')
        self.assertFalse(application.paper_type_determined)

    def test_the_default_rule_asks_the_officer_to_verify(self):
        application = self.submit()
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)

        response = self.client.get(f'/applications/{application.pk}/review/')
        self.assertContains(response, 'Unable to determine')
        self.assertContains(
            response,
            'Paper type could not be determined from the application. Please '
            'verify the paper type.',
        )

    def test_the_officer_may_still_carry_on(self):
        application = self.submit()
        self.post_review(application)
        application.refresh_from_db()

        self.assertEqual(application.processing_status, ProcessingStatus.CONFIRMED)
        for exam in application.exam_records.all():
            self.assertEqual(exam.paper_type, 'b737')

    @override_settings(PAPER_TYPE_UNRESOLVED_POLICY='block')
    def test_the_rule_is_configurable(self):
        application = self.submit()
        self.assertEqual(
            application.processing_status, ProcessingStatus.PAPER_MISMATCH
        )
        self.assertEqual(
            application.error_message,
            'Paper type could not be determined from the application. Please '
            'verify the paper type.',
        )

    def test_an_unresolved_paper_is_audited_either_way(self):
        self.submit()
        self.assertTrue(
            ActivityLog.objects.filter(
                action=ActivityLog.Action.PAPER_TYPE_UNRESOLVED
            ).exists()
        )


class FlightDispatchSelectionTests(ReviewHelperMixin, WorkflowTestCase):
    letter_text = FLIGHT_DISPATCH_LETTER

    def test_either_paper_may_be_selected(self):
        for index, paper in enumerate(('paper_1', 'paper_2')):
            with self.subTest(paper=paper):
                self.set_ocr_text(
                    letter=FLIGHT_DISPATCH_LETTER, receipt=self.receipt_text
                )
                self.submit_application(
                    exam_category='flight_dispatch', paper_type=paper
                )
                application = Application.objects.order_by('-created_at').first()
                self.assertEqual(application.paper_type, paper)
                self.assertEqual(
                    application.processing_status, ProcessingStatus.REVIEW
                )
                self.post_review(
                    application, receipt_number=f'NCAA/2026/0080{index:02d}'
                )

    def test_the_named_paper_must_agree_with_the_selection(self):
        self.set_ocr_text(
            letter=FLIGHT_DISPATCH_PAPER_2_LETTER, receipt=self.receipt_text
        )
        self.submit_application(
            exam_category='flight_dispatch', paper_type='paper_1'
        )
        application = Application.objects.get()
        self.assertEqual(
            application.processing_status, ProcessingStatus.PAPER_MISMATCH
        )
        self.assertEqual(application.detected_paper_type, 'paper_2')
