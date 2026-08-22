"""Candidate and receipt extraction across the letter formats officers meet."""
from django.test import SimpleTestCase, override_settings

from applications.services.extraction import ApplicationExtractor, ReceiptExtractor
from applications.services.ocr import OCRLine, OCRResult


def result(text, confidence=97.0):
    return OCRResult(
        lines=[OCRLine(line, confidence, 1) for line in text.splitlines()],
        page_count=1,
    )


class CandidateExtractionTests(SimpleTestCase):
    def setUp(self):
        self.extractor = ApplicationExtractor()

    def names(self, text, confidence=97.0):
        return [c.name for c in self.extractor.extract_candidates(result(text, confidence))]

    def test_single_candidate(self):
        text = """APPLICATION FOR FLIGHT DISPATCH EXAMINATION
We hereby submit the following candidate for the examination:
1. TUNDE BAKARE
Yours sincerely,"""
        self.assertEqual(self.names(text), ['TUNDE BAKARE'])

    def test_multiple_candidates_numbered(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We hereby submit the following candidates for the examination:
1. JOHN ADEWALE
2. DAVID OKORO
3. MICHAEL IBRAHIM
4. PETER WILLIAMS
Yours faithfully,"""
        self.assertEqual(
            self.names(text),
            ['JOHN ADEWALE', 'DAVID OKORO', 'MICHAEL IBRAHIM', 'PETER WILLIAMS'],
        )

    def test_mixed_numbering_styles(self):
        text = """APPLICATION FOR CABIN CREW EXAMINATION
We nominate the following candidates:
1) Blessing Eze
2.  Musa Danjuma
(3) Kelechi Obi
Thank you."""
        self.assertEqual(
            self.names(text), ['Blessing Eze', 'Musa Danjuma', 'Kelechi Obi']
        )

    def test_bulleted_list(self):
        text = """APPLICATION FOR CABIN CREW EXAMINATION
Please find the list of candidates below:
- Amina Bello
- Chidi Okafor
* Grace Nwosu
Yours faithfully,"""
        self.assertEqual(self.names(text), ['Amina Bello', 'Chidi Okafor', 'Grace Nwosu'])

    def test_pipe_delimited_table(self):
        text = """APPLICATION FOR AME EXAMINATION
The following candidates are presented:
| S/N | NAME             |
| 1   | IBRAHIM MUSA     |
| 2   | YUSUF ABDULLAHI  |
Thank you"""
        self.assertEqual(self.names(text), ['IBRAHIM MUSA', 'YUSUF ABDULLAHI'])

    def test_space_aligned_table_with_reference_column(self):
        """Wide gaps split a name across columns; it must be rejoined."""
        text = """APPLICATION FOR PILOT EXAMINATION
Names of candidates:
1     ADAEZE  NWOSU        NCAA-001
2     FATIMA GARBA         NCAA-002
Regards"""
        self.assertEqual(self.names(text), ['ADAEZE NWOSU', 'FATIMA GARBA'])

    def test_names_on_bare_lines_are_found_but_flagged(self):
        text = """APPLICATION FOR PILOT EXAMINATION

OLUWASEUN ADEBAYO
NGOZI ANYANWU

Yours faithfully"""
        matches = self.extractor.extract_candidates(result(text))
        self.assertEqual([m.name for m in matches], ['OLUWASEUN ADEBAYO', 'NGOZI ANYANWU'])
        self.assertTrue(all(m.needs_review for m in matches))

    def test_honorifics_are_stripped(self):
        text = """APPLICATION FOR AME EXAMINATION
The under-listed candidates apply:
1. Mr. Segun Alabi
2. Engr. Halima Sadiq
Yours faithfully"""
        self.assertEqual(self.names(text), ['Segun Alabi', 'Halima Sadiq'])

    def test_company_and_boilerplate_lines_are_not_candidates(self):
        text = """APPLICATION FOR AME EXAMINATION
The under-listed candidates apply:
1. Segun Alabi
2. Skyway Aviation Limited
3. Training Manager
4. Yours Faithfully
Yours faithfully"""
        self.assertEqual(self.names(text), ['Segun Alabi'])

    def test_lines_containing_digits_are_not_candidates(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We submit the following candidates:
1. JOHN ADEWALE
2. Suite 4 Airport Road
Yours faithfully"""
        self.assertEqual(self.names(text), ['JOHN ADEWALE'])

    def test_duplicate_names_are_collapsed(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We submit the following candidates:
1. JOHN ADEWALE
2. JOHN ADEWALE
Yours faithfully"""
        self.assertEqual(self.names(text), ['JOHN ADEWALE'])

    def test_the_list_stops_at_the_sign_off(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We submit the following candidates:
1. JOHN ADEWALE
Yours faithfully,
Bola Ogunleye"""
        self.assertEqual(self.names(text), ['JOHN ADEWALE'])

    def test_no_candidates_in_a_letter_without_names(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We write to enquire about the next examination date.
Yours faithfully,"""
        self.assertEqual(self.names(text), [])

    @override_settings(OCR_CONFIDENCE_THRESHOLD=80.0)
    def test_low_confidence_names_are_flagged_for_review(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We submit the following candidates:
1. JOHN ADEWALE"""
        matches = self.extractor.extract_candidates(result(text, confidence=62.0))
        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0].needs_review)
        self.assertIn('62%', matches[0].reason)

    @override_settings(OCR_CONFIDENCE_THRESHOLD=80.0)
    def test_high_confidence_names_are_not_flagged(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We submit the following candidates:
1. JOHN ADEWALE"""
        matches = self.extractor.extract_candidates(result(text, confidence=98.0))
        self.assertFalse(matches[0].needs_review)

    def test_company_name_is_read_from_the_letterhead(self):
        text = """SKYWAY AVIATION TRAINING ACADEMY LIMITED
12 Airport Road, Lagos
APPLICATION FOR PILOT EXAMINATION"""
        self.assertEqual(
            self.extractor.extract_company(result(text)),
            'SKYWAY AVIATION TRAINING ACADEMY LIMITED',
        )

    def test_the_recipient_is_not_taken_as_the_applicant(self):
        text = """The Director General
Nigeria Civil Aviation Authority
APPLICATION FOR PILOT EXAMINATION"""
        self.assertEqual(self.extractor.extract_company(result(text)), '')


class ReceiptExtractionTests(SimpleTestCase):
    def setUp(self):
        self.extractor = ReceiptExtractor()

    def value(self, text, confidence=97.0):
        return self.extractor.extract_receipt_number(result(text, confidence))

    def test_labelled_receipt_number(self):
        match = self.value('Receipt No: NCAA/2026/004821')
        self.assertEqual(match.value, 'NCAA/2026/004821')
        self.assertTrue(match.found)

    def test_spacing_around_separators_is_removed(self):
        self.assertEqual(
            self.value('Receipt No : NCAA / 2026 / 004821').value, 'NCAA/2026/004821'
        )

    def test_variant_labels(self):
        cases = [
            ('RECEIPT NUMBER : ABC-9931', 'ABC-9931'),
            ('Receipt #: RCP10022', 'RCP10022'),
            ('Payment Reference: TRX55512', 'TRX55512'),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.value(text).value, expected)

    def test_bare_ncaa_reference_is_found_without_a_label(self):
        text = """OFFICIAL PAYMENT RECEIPT
NCAA/2026/004821
Amount: NGN 50,000"""
        self.assertEqual(self.value(text).value, 'NCAA/2026/004821')

    def test_labelled_number_outranks_a_weaker_reference(self):
        text = """Transaction No: TRX0001
Receipt No: NCAA/2026/004821"""
        self.assertEqual(self.value(text).value, 'NCAA/2026/004821')

    def test_missing_receipt_number_is_reported(self):
        match = self.value('OFFICIAL PAYMENT RECEIPT\nAmount paid in full')
        self.assertFalse(match.found)
        self.assertTrue(match.needs_review)

    def test_unreadable_receipt_is_reported(self):
        match = self.value('')
        self.assertFalse(match.found)
        self.assertTrue(match.needs_review)

    @override_settings(OCR_CONFIDENCE_THRESHOLD=80.0)
    def test_low_confidence_receipt_is_flagged(self):
        match = self.value('Receipt No: NCAA/2026/004821', confidence=55.0)
        self.assertTrue(match.found)
        self.assertTrue(match.needs_review)

    def test_characters_are_never_substituted(self):
        """O is not silently corrected to 0: that would corrupt a good read."""
        self.assertEqual(self.value('Receipt No: NCAA/2O26/OO4821').value, 'NCAA/2O26/OO4821')


class RealScanRegressionTests(SimpleTestCase):
    """Lines taken verbatim from genuine Tesseract output on scanned letters.

    Both shapes below were missed by earlier versions of the parser and were
    only found by running real scans through the pipeline.
    """

    def setUp(self):
        self.extractor = ApplicationExtractor()

    def names(self, text, confidence=95.0):
        return [c.name for c in self.extractor.extract_candidates(result(text, confidence))]

    def test_table_columns_flattened_to_a_single_space(self):
        """Recognition normalises whitespace, so "1    NAME" arrives as "1 NAME"."""
        text = """APPLICATION FOR AME EXAMINATION
The following candidates are presented for the examination:
S/N CANDIDATE NAME
1 IBRAHIM MUSA
2 YUSUF ABDULLAHI
Kindly schedule the above candidates accordingly."""
        self.assertEqual(self.names(text), ['IBRAHIM MUSA', 'YUSUF ABDULLAHI'])

    def test_stray_marks_between_the_number_and_the_name(self):
        """A speck on the page becomes a token; it must not lose the candidate."""
        text = """APPLICATION FOR FLIGHT DISPATCH EXAMINATION
We write to present the under-listed candidates for the
Flight Dispatch examination:
1. . TUNDE BAKARE
2. | HALIMA SADIQ
3. CHINEDU EZEKWESILI
Kindly schedule the above candidates accordingly."""
        self.assertEqual(
            self.names(text),
            ['TUNDE BAKARE', 'HALIMA SADIQ', 'CHINEDU EZEKWESILI'],
        )

    def test_an_address_is_not_read_as_a_candidate(self):
        """The bare-number form must not turn a letterhead into a candidate."""
        text = """SKYWAY AVIATION TRAINING ACADEMY LIMITED
12 Airport Road, Ikeja
4 Aminu Kano Crescent
Dear Sir,
APPLICATION FOR PILOT EXAMINATION
We hereby submit the following candidates for the examination:
1 JOHN ADEWALE
Yours faithfully,"""
        self.assertEqual(self.names(text), ['JOHN ADEWALE'])

    def test_bare_numbers_are_ignored_outside_a_candidate_block(self):
        """With no introducing phrase, "12 Airport Road" stays an address."""
        text = """SKYWAY AVIATION TRAINING ACADEMY LIMITED
12 Airport Road, Ikeja
4 Marina Close
APPLICATION FOR PILOT EXAMINATION"""
        self.assertEqual(self.names(text), [])

    def test_the_signatory_block_is_not_read_as_a_candidate(self):
        text = """APPLICATION FOR PILOT EXAMINATION
We hereby submit the following candidates for the examination:
1. JOHN ADEWALE
Kindly schedule the above candidates accordingly.
Yours faithfully,
Bola Ogunleye
Training Manager"""
        self.assertEqual(self.names(text), ['JOHN ADEWALE'])


class ReceiptFieldTargetingTests(SimpleTestCase):
    """An NCAA receipt carries several numbers; only one is the right one."""

    def setUp(self):
        self.extractor = ReceiptExtractor()

    def value(self, text, confidence=95.0):
        return self.extractor.extract_receipt_number(result(text, confidence))

    def test_the_official_receipt_number_wins_over_other_fields(self):
        text = """NIGERIAN CIVIL AVIATION AUTHORITY
Official Receipt No: 0125002
DATE: 02/07/2025
INVOICE NO: 5100380142033
PERIOD: 01/07/2025
AMOUNT IN FIGURES: 10,000.00"""
        self.assertEqual(self.value(text).value, '0125002')

    def test_an_invoice_number_is_never_the_receipt_number(self):
        text = """OFFICIAL RECEIPT
INVOICE NO: 5100380142033
PERIOD: 01/07/2025"""
        self.assertNotEqual(self.value(text).value, '5100380142033')

    def test_a_date_is_not_taken_as_the_receipt_number(self):
        text = 'OFFICIAL RECEIPT\nDATE: 02/07/2025'
        match = self.value(text)
        self.assertNotIn('2025', match.value)

    def test_a_bare_year_is_rejected(self):
        self.assertFalse(self.extractor._is_plausible('2025'))
        self.assertTrue(self.extractor._is_plausible('0125002'))

    def test_an_over_long_number_is_rejected(self):
        """The invoice number on an NCAA receipt runs to thirteen digits."""
        self.assertFalse(self.extractor._is_plausible('5100380142033'))

    def test_official_receipt_label_outranks_a_plain_reference(self):
        text = """Payment Reference: TRX0001
Official Receipt No: 0125002"""
        self.assertEqual(self.value(text).value, '0125002')

    def test_a_missing_receipt_number_is_reported_not_guessed(self):
        text = """OFFICIAL RECEIPT
DATE: 02/07/2025
AMOUNT: 10,000.00"""
        match = self.value(text)
        self.assertFalse(match.found)
        self.assertTrue(match.needs_review)
