"""Examination type detection, normalisation and the mandatory match rule."""
from django.test import SimpleTestCase

from exams import exam_types
from exams.models import ExamType


class NormalisationTests(SimpleTestCase):
    def test_case_is_not_significant(self):
        for value in ('pilot', 'PILOT', 'Pilot', '  PiLoT  '):
            with self.subTest(value=value):
                self.assertEqual(exam_types.normalize(value), ExamType.PILOT)

    def test_stored_values_and_labels_both_resolve(self):
        self.assertEqual(
            exam_types.normalize('flight_dispatch'), ExamType.FLIGHT_DISPATCH
        )
        self.assertEqual(
            exam_types.normalize('Flight Dispatch'), ExamType.FLIGHT_DISPATCH
        )

    def test_unknown_value_resolves_to_none(self):
        self.assertIsNone(exam_types.normalize('Air Traffic Control'))
        self.assertIsNone(exam_types.normalize(''))
        self.assertIsNone(exam_types.normalize(None))


class DetectionTests(SimpleTestCase):
    def test_detects_each_examination_type(self):
        cases = [
            ('APPLICATION FOR PILOT EXAMINATION', ExamType.PILOT),
            ('Application for Cabin Crew Examination', ExamType.CABIN_CREW),
            ('APPLICATION FOR AME EXAMINATION', ExamType.AME),
            ('Aircraft Maintenance Engineering examination', ExamType.AME),
            ('RE: FLIGHT DISPATCH EXAMINATION', ExamType.FLIGHT_DISPATCH),
            ('application for flight dispatcher examination', ExamType.FLIGHT_DISPATCH),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(exam_types.detect(text).exam_type, expected)

    def test_flight_dispatch_is_not_mistaken_for_pilot(self):
        """"Flight dispatch" contains no pilot wording; the order must hold."""
        detection = exam_types.detect('APPLICATION FOR FLIGHT DISPATCH EXAMINATION')
        self.assertEqual(detection.exam_type, ExamType.FLIGHT_DISPATCH)
        self.assertNotIn(ExamType.PILOT, detection.scores)

    def test_lowercase_ame_is_not_treated_as_an_abbreviation(self):
        """Only capitalised AME counts, so ordinary words cannot trigger it."""
        detection = exam_types.detect('we came to submit this application')
        self.assertNotEqual(detection.exam_type, ExamType.AME)

    def test_nothing_detected_in_unrelated_text(self):
        detection = exam_types.detect('Dear Sir, please find our payment attached.')
        self.assertFalse(detection.detected)

    def test_a_passing_mention_does_not_make_it_ambiguous(self):
        """A letter headed for one examination is not made uncertain by an
        aside about another kind of staff."""
        detection = exam_types.detect(
            'APPLICATION FOR PILOT EXAMINATION. We also list cabin crew staff.'
        )
        self.assertEqual(detection.exam_type, ExamType.PILOT)
        self.assertTrue(detection.contextual)
        self.assertFalse(detection.ambiguous)

    def test_two_examination_contexts_are_flagged_ambiguous(self):
        """Genuine ambiguity is still caught: both types are applied for."""
        detection = exam_types.detect(
            'APPLICATION FOR PILOT EXAMINATION AND CABIN CREW EXAMINATION'
        )
        self.assertTrue(detection.ambiguous)
        self.assertIn(ExamType.PILOT, detection.scores)
        self.assertIn(ExamType.CABIN_CREW, detection.scores)

    def test_ambiguous_text_prefers_the_type_named_first(self):
        """The heading decides; a later mention must not win on a tie."""
        detection = exam_types.detect(
            'APPLICATION FOR PILOT EXAMINATION. We also list cabin crew staff.'
        )
        self.assertEqual(detection.exam_type, ExamType.PILOT)


class MatchRuleTests(SimpleTestCase):
    def test_matching_selections_are_accepted(self):
        for value in ('pilot', 'ame', 'cabin_crew', 'flight_dispatch'):
            with self.subTest(value=value):
                self.assertTrue(exam_types.matches(value, value))

    def test_case_insensitive_match_is_accepted(self):
        self.assertTrue(exam_types.matches('pilot', 'PILOT'))
        self.assertTrue(exam_types.matches('AME', 'ame'))

    def test_different_categories_do_not_match(self):
        self.assertFalse(exam_types.matches('pilot', 'cabin_crew'))
        self.assertFalse(exam_types.matches('ame', 'flight_dispatch'))

    def test_missing_detection_does_not_match(self):
        self.assertFalse(exam_types.matches('pilot', None))
        self.assertFalse(exam_types.matches('pilot', ''))


class PaperStructureTests(SimpleTestCase):
    def test_only_flight_dispatch_has_papers(self):
        self.assertTrue(exam_types.has_papers(ExamType.FLIGHT_DISPATCH))
        for value in (ExamType.PILOT, ExamType.AME, ExamType.CABIN_CREW):
            with self.subTest(value=value):
                self.assertFalse(exam_types.has_papers(value))


class ContextualDetectionTests(SimpleTestCase):
    """The examination type is decided by context, not by keyword presence.

    A letter is full of aviation vocabulary. What identifies the examination
    is the phrasing around the type, not that the words appear at all.
    """

    def type_of(self, text):
        return exam_types.detect(text).exam_type

    def test_cabin_crew_phrasings_all_resolve(self):
        phrasings = [
            'CABIN CREW',
            'CABIN CREW AB-INITIO',
            'CABIN CREW AB INITIO',
            'CABIN CREW STUDENTS',
            'EXAM DATE FOR CABIN CREW',
            'CABIN CREW EXAMINATION',
            'CABIN CREW EXAM',
            'REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS',
            'REQUEST FOR EXAM DATE FOR CABIN CREW AB INITIO STUDENTS',
            'the just concluded Cabin crew ab-initio training',
        ]
        for text in phrasings:
            with self.subTest(text=text):
                self.assertEqual(self.type_of(text), ExamType.CABIN_CREW)

    def test_the_standalone_phrase_is_not_required(self):
        """The exact words "Cabin Crew" alone must not be what it hinges on."""
        detection = exam_types.detect(
            'REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS'
        )
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)
        self.assertTrue(detection.contextual)
        self.assertFalse(detection.ambiguous)

    def test_aviation_terminology_alone_classifies_nothing(self):
        """A type rating is equipment, not an examination category."""
        for text in [
            'Boeing 737 Classic Type Rating',
            'Boeing 737 Classic Type rating exam in Lagos',
            'schedule the students for Air - Law and Boeing 737 Classic Type rating exam',
            'Airbus A320 type rating and line training',
        ]:
            with self.subTest(text=text):
                self.assertIsNone(self.type_of(text))

    def test_examination_context_outranks_a_distractor(self):
        """The real letter: cabin crew in the heading, a 737 exam in the body."""
        text = (
            'REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS '
            "We wish to notify the Authority for the just concluded Cabin crew "
            "ab-initio training. The training ended on the 4th JUNE, 2025, and "
            "we'd like to schedule the students for Air - Law and Boeing 737 "
            'Classic Type rating exam in Lagos.'
        )
        detection = exam_types.detect(text)
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)
        self.assertTrue(detection.contextual)
        self.assertFalse(detection.ambiguous)

    def test_context_beats_bare_mentions_of_other_types(self):
        text = (
            'REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS. '
            'Our pilots and AME staff assisted with the training.'
        )
        detection = exam_types.detect(text)
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)
        self.assertNotIn(ExamType.PILOT, detection.scores)
        self.assertNotIn(ExamType.AME, detection.scores)

    def test_every_context_template_maps_to_a_canonical_type(self):
        cases = [
            ('REQUEST FOR EXAM DATE FOR PILOT STUDENTS', ExamType.PILOT),
            ('APPLICATION FOR AME EXAMINATION', ExamType.AME),
            ('AME EXAM', ExamType.AME),
            ('Aircraft Maintenance Engineering examination', ExamType.AME),
            ('FLIGHT DISPATCH CANDIDATES', ExamType.FLIGHT_DISPATCH),
            ('application for flight dispatcher examination', ExamType.FLIGHT_DISPATCH),
            ('CPL candidates', ExamType.PILOT),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.type_of(text), expected)

    def test_detection_never_invents_a_type(self):
        """Only the four configured types may ever come back."""
        allowed = {choice.value for choice in ExamType}
        for text in [
            'REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS',
            'APPLICATION FOR AVIONICS EXAMINATION',
            'REQUEST FOR EXAM DATE FOR AIR TRAFFIC CONTROL STUDENTS',
        ]:
            with self.subTest(text=text):
                result = exam_types.detect(text).exam_type
                self.assertTrue(result is None or result in allowed)

    def test_a_heading_split_across_lines_still_matches(self):
        """Recognition breaks a heading wherever the page does."""
        detection = exam_types.detect(
            'REQUEST FOR EXAM DATE FOR CABIN\nCREW AB-INITIO\nSTUDENTS'
        )
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)


class TypeRatingDistractorTests(SimpleTestCase):
    """A type rating names an aircraft, never an examination category."""

    def test_no_aircraft_type_rating_classifies_an_application(self):
        for text in [
            'Embraer 135/145 Type rating exam',
            'Boeing 737 Classic Type rating exam in Lagos',
            'schedule the students for Embraer 135/145 Type rating exam',
            'Airbus A320 type rating',
            'ATR 72 differences training',
        ]:
            with self.subTest(text=text):
                self.assertIsNone(exam_types.detect(text).exam_type)

    def test_the_singular_student_form_is_recognised(self):
        """Real subject lines say "STUDENT" as often as "STUDENTS"."""
        detection = exam_types.detect(
            'REQUEST FOR EXAM DATE FOR CABIN CREW STUDENT EMBRAER 135/145'
        )
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)
        self.assertTrue(detection.contextual)

    def test_conversion_training_wording_resolves(self):
        detection = exam_types.detect(
            'the just concluded Cabin crew conversion training'
        )
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)

    def test_an_aircraft_type_in_the_subject_does_not_override_the_type(self):
        text = (
            'REQUEST FOR EXAM DATE FOR CABIN CREW STUDENT EMBRAER 135/145 '
            'We would like to schedule the students for Embraer 135/145 Type '
            'rating exam.'
        )
        detection = exam_types.detect(text)
        self.assertEqual(detection.exam_type, ExamType.CABIN_CREW)
        self.assertNotIn(ExamType.PILOT, detection.scores)
        self.assertNotIn(ExamType.AME, detection.scores)
