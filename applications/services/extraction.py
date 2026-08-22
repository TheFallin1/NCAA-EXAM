"""Information extraction.

OCR yields text; it does not know which of that text is a candidate name, an
examination type, or a receipt number. This module is the layer that decides,
using explicit rules rather than a model, so that every decision is inspectable
and every rejection can be explained to the officer.

Nothing here is trusted blindly: everything it produces is shown to the officer
for verification before an examination record exists.
"""
import re
import unicodedata
from dataclasses import dataclass

from django.conf import settings

from exams import exam_types

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Tokens that prove a line is not a person's name. Letter boilerplate,
# organisation words, and examination vocabulary all end up on lines that
# otherwise look name-shaped, especially in tables.
_NAME_STOPWORDS = {
    # organisations
    'LTD', 'LIMITED', 'PLC', 'INC', 'COMPANY', 'CO', 'AIRLINE', 'AIRLINES',
    'AIRWAYS', 'AIR', 'AVIATION', 'TRAINING', 'ACADEMY', 'CENTRE', 'CENTER',
    'SCHOOL', 'COLLEGE', 'INSTITUTE', 'SERVICES', 'SERVICE', 'ENGINEERING',
    'MAINTENANCE', 'AIRCRAFT', 'ORGANISATION', 'ORGANIZATION', 'DEPARTMENT',
    'UNIT', 'AUTHORITY', 'NIGERIA', 'NIGERIAN', 'CIVIL', 'NCAA',
    'HEADQUARTERS', 'CORPORATE', 'GENERAL', 'ATTN', 'ATTENTION', 'MGT',
    'MANAGEMENT', 'BRANCH', 'ORIGINAL', 'DUPLICATE',
    # address structure
    'ROAD', 'STREET', 'AVENUE', 'CLOSE', 'CRESCENT', 'PLOT', 'SUITE',
    'LANE', 'ESTATE', 'HANGAR', 'AIRPORT', 'BOULEVARD', 'TERRACE',
    # letter boilerplate
    'DEAR', 'SIR', 'MADAM', 'YOURS', 'FAITHFULLY', 'SINCERELY', 'REGARDS',
    'SUBJECT', 'RE', 'REF', 'REFERENCE', 'DATE', 'DATED', 'PLEASE', 'KINDLY',
    'THANK', 'THANKS', 'YOU', 'WE', 'OUR', 'HEREBY', 'SUBMIT', 'SUBMITTED',
    'FOLLOWING', 'ATTACHED', 'BELOW', 'ABOVE', 'SIGNED', 'SIGNATURE', 'TITLE',
    'POSITION', 'DESIGNATION', 'MANAGER', 'DIRECTOR', 'HEAD', 'OFFICER',
    'THE', 'FOR', 'AND', 'OF', 'TO', 'FROM', 'WITH', 'THAT', 'THIS', 'ARE',
    'IS', 'BE', 'AS', 'ON', 'IN', 'AT', 'BY',
    # examination vocabulary
    'APPLICATION', 'APPLICATIONS', 'EXAMINATION', 'EXAMINATIONS', 'EXAM',
    'EXAMS', 'CANDIDATE', 'CANDIDATES', 'NAME', 'NAMES', 'PILOT', 'PILOTS',
    'CABIN', 'CREW', 'FLIGHT', 'DISPATCH', 'DISPATCHER', 'AME', 'PAPER',
    'PAPERS', 'VENUE', 'SCHEDULE', 'LICENCE', 'LICENSE',
    # receipt vocabulary
    'RECEIPT', 'PAYMENT', 'PAID', 'AMOUNT', 'TOTAL', 'NAIRA', 'NGN', 'INVOICE',
    'TELLER', 'BANK', 'TRANSACTION', 'NUMBER', 'NO', 'SN', 'SERIAL',
}

# Phrases that introduce the candidate list.
_LIST_TRIGGERS = (
    r'following\s+candidates?',
    r'candidates?\s+(?:are|is|for|listed|below|named)',
    r'list\s+of\s+(?:the\s+)?candidates?',
    r'names?\s+of\s+(?:the\s+)?candidates?',
    r'under[\s-]?listed',
    r'submit\s+the\s+following',
    r'present\s+the\s+following',
    r'nominate\s+the\s+following',
    r'as\s+follows',
    # "Please find students' names below:" -- the apostrophe frequently comes
    # back from recognition as a stray character, so it is not matched on.
    r'names?\s+(?:are\s+)?(?:listed\s+)?below',
    r'find\s+(?:the\s+)?(?:students?|candidates?|under)',
    r'students?\s+(?:are\s+)?(?:listed\s+)?(?:below|as)',
)

# Phrases that close the candidate list.
_LIST_TERMINATORS = (
    r'yours\s+faithfully',
    r'yours\s+sincerely',
    r'thank(?:\s+you)?',
    r'best\s+regards',
    r'^\s*regards\s*$',
    r'we\s+(?:look\s+forward|await|shall)',
    r'signature',
    r'^\s*signed\s*$',
)

_NUMBERED = re.compile(r'^\(?\s*(\d{1,3})\s*[.)\]:\-]\s*(.+)$')
# A serial number with no punctuation after it, e.g. "1 IBRAHIM MUSA".
# Recognition normalises whitespace, so the column gap in a tabulated list is
# routinely flattened to a single space. Only applied inside a candidate block:
# outside one it would happily read "12 Airport Road" as a candidate.
_NUMBERED_BARE = re.compile(r'^\(?\s*(\d{1,3})\s+(.+)$')
_BULLETED = re.compile(r'^\s*[-•·*‣◦]\s+(.+)$')
_TOKEN = re.compile(r"^[A-Za-z][A-Za-z'\-]*\.?$")
_INITIAL = re.compile(r'^[A-Za-z]\.?$')
_HONORIFICS = {'MR', 'MRS', 'MISS', 'MS', 'DR', 'ENGR', 'CAPT', 'CAPTAIN', 'PROF'}
# Stray marks recognition leaves in a line, e.g. "2. | HALIMA SADIQ".
_NOISE_CHARS = r'|.,;:*_/\()[]{}<>"' + "'"


@dataclass
class CandidateMatch:
    name: str
    confidence: float = None
    needs_review: bool = False
    reason: str = ''


@dataclass
class ReceiptMatch:
    value: str = ''
    confidence: float = None
    needs_review: bool = False
    evidence: str = ''

    @property
    def found(self):
        return bool(self.value)


def _clean_text(value):
    """Normalise unicode punctuation the scanner or OCR may have introduced.

    Runs of spaces are deliberately preserved: wide gaps are what marks the
    column boundaries in a tabulated candidate list, so collapsing them here
    would flatten the table before it can be parsed.
    """
    if not value:
        return ''
    text = unicodedata.normalize('NFKC', str(value))
    text = text.replace('‘', "'").replace('’', "'")
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('–', '-').replace('—', '-')
    return text.replace('\t', '  ').strip()


def _collapse_spaces(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def _matches_any(text, patterns):
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


class ApplicationExtractor:
    """Reads the application letter."""

    def extract_exam_type(self, ocr_result):
        """Detect the examination type the letter is written for."""
        return exam_types.detect(ocr_result.text)

    def extract_candidates(self, ocr_result):
        """Pull candidate names out of the letter.

        Letters vary: numbered lists, bulleted lists, plain lines, and simple
        tables all occur. The parser tries each shape per line rather than
        assuming one format for the whole document.
        """
        threshold = settings.OCR_CONFIDENCE_THRESHOLD
        lines = [line for line in ocr_result.lines if line.text and line.text.strip()]

        start, saw_trigger = self._find_list_start(lines)
        matches = []
        seen = set()

        for line in lines[start:]:
            text = _clean_text(line.text)
            if not text:
                continue
            if _matches_any(text, _LIST_TERMINATORS):
                break

            for raw_name, structured in self._names_in_line(text, saw_trigger):
                name, ok, soft, reason = self._evaluate_name(raw_name)
                if not ok:
                    continue

                key = re.sub(r'\s+', ' ', name).upper()
                if key in seen:
                    continue
                seen.add(key)

                confidence = line.confidence
                low_confidence = confidence is not None and confidence < threshold
                # A name found with no list marker and no introducing phrase is
                # a weaker signal, so it is surfaced for a second look.
                weak_structure = not structured and not saw_trigger

                reasons = []
                if low_confidence:
                    reasons.append(f'OCR confidence {confidence:.0f}%')
                if soft:
                    reasons.append(reason)
                if weak_structure:
                    reasons.append('name found without a list marker')

                matches.append(
                    CandidateMatch(
                        name=name,
                        confidence=confidence,
                        needs_review=bool(reasons),
                        reason='; '.join(reasons),
                    )
                )

        return matches

    def extract_company(self, ocr_result):
        """Best-effort organisation name from the letterhead.

        Only a convenience: the officer can always correct it on the review
        screen, and nothing blocks if it is not found.
        """
        organisation_words = (
            'LIMITED', 'LTD', 'PLC', 'AIRLINE', 'AIRLINES', 'AIRWAYS',
            'AVIATION', 'ACADEMY', 'TRAINING', 'COLLEGE', 'INSTITUTE',
            'SERVICES', 'CENTRE', 'CENTER', 'SCHOOL',
        )

        # The signature block is the most reliable statement of who is
        # applying: Nigerian business letters sign off "For: <organisation>".
        for line in ocr_result.lines:
            text = _collapse_spaces(_clean_text(line.text))
            match = re.match(r'^for\s*[:\-]\s*(.{3,120})$', text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(' .,:;-')
                if candidate and not self._is_recipient(candidate.upper()):
                    return candidate

        # Otherwise fall back to the letterhead at the top of the page.
        for line in ocr_result.lines[:15]:
            text = _collapse_spaces(_clean_text(line.text))
            if not text or len(text) > 120:
                continue
            upper = text.upper()
            if self._is_recipient(upper):
                continue
            if any(word in upper.split() or word in upper for word in organisation_words):
                return text
        return ''

    def _is_recipient(self, upper):
        """True for lines addressing NCAA rather than naming the applicant."""
        markers = (
            'NIGERIA CIVIL AVIATION AUTHORITY',
            'NIGERIAN CIVIL AVIATION AUTHORITY',
            'DIRECTOR GENERAL',
            'CORPORATE HEADQUARTERS',
            'INTERNATIONAL AIRPORT',
            'ATTN',
        )
        return upper.strip() == 'NCAA' or any(marker in upper for marker in markers)

    # -- internals ---------------------------------------------------------
    def _find_list_start(self, lines):
        """Index to start scanning from, and whether a trigger phrase was seen."""
        for index, line in enumerate(lines):
            if _matches_any(_clean_text(line.text), _LIST_TRIGGERS):
                return index + 1, True
        return 0, False

    def _names_in_line(self, text, in_candidate_block=False):
        """Return [(candidate text, had_list_structure)] for one line."""
        numbered = _NUMBERED.match(text)
        if numbered:
            return [(numbered.group(2).strip(), True)]

        bulleted = _BULLETED.match(text)
        if bulleted:
            return [(bulleted.group(1).strip(), True)]

        # Strip a bare serial number and carry on: the rest of the line may
        # still be a multi-column row, so this must not short-circuit.
        structured = False
        if in_candidate_block:
            bare = _NUMBERED_BARE.match(text)
            if bare:
                text = bare.group(2).strip()
                structured = True

        # Table rows: pipe-delimited, or columns separated by wide gaps.
        if '|' in text:
            return self._names_in_columns(
                [cell.strip() for cell in text.split('|') if cell.strip()]
            )

        columns = re.split(r'\s{2,}', text)
        if len(columns) > 1:
            return self._names_in_columns(columns)

        return [(text, structured)]

    def _names_in_columns(self, columns):
        """Pick the name out of a table row.

        Columns holding digits are serial numbers or examination references,
        never names. If no single remaining column is name-shaped, the row is
        assumed to be one name that wide OCR spacing split apart, so the
        remaining columns are rejoined.
        """
        cleaned = []
        for column in columns:
            stripped = re.sub(r'^\s*\d{1,3}\s*[.)\]:\-]?\s*', '', column).strip()
            if stripped:
                cleaned.append(stripped)

        wordy = [column for column in cleaned if not re.search(r'\d', column)]
        valid = [(column, True) for column in wordy if self._evaluate_name(column)[1]]
        if valid:
            return valid
        if len(wordy) > 1:
            return [(' '.join(wordy), True)]
        return [(column, True) for column in wordy]

    def _evaluate_name(self, raw):
        """Validate a candidate name.

        Returns (cleaned name, accepted, needs_review, reason).
        """
        text = _clean_text(raw)
        # Drop trailing annotations a table might carry, e.g. "JOHN ADEWALE -"
        text = text.strip(' \t.,;:-–')
        if not text:
            return '', False, False, ''

        if re.search(r'\d', text):
            return '', False, False, ''

        # Strip stray marks off each part, and discard any part that was
        # nothing but a mark, so "| HALIMA SADIQ" reads as "HALIMA SADIQ".
        tokens = []
        for token in text.split():
            token = token.strip(_NOISE_CHARS)
            if token:
                tokens.append(token)

        # Honorifics are not part of the name of record.
        while tokens and tokens[0].strip('.').upper() in _HONORIFICS:
            tokens = tokens[1:]

        if not (2 <= len(tokens) <= 5):
            return '', False, False, ''

        for token in tokens:
            if not _TOKEN.match(token):
                return '', False, False, ''
            if token.strip('.').upper() in _NAME_STOPWORDS:
                return '', False, False, ''

        name = ' '.join(tokens)

        # Soft signals: accepted, but the officer is asked to look.
        initials = sum(1 for token in tokens if _INITIAL.match(token))
        if initials and len(tokens) - initials < 2:
            return name, True, True, 'mostly initials'
        short = [t for t in tokens if len(t.strip('.')) < 3 and not _INITIAL.match(t)]
        if short:
            return name, True, True, 'unusually short name part'

        return name, True, False, ''


class ReceiptExtractor:
    """Reads the payment receipt.

    Only one field is wanted: the Official Receipt Number. An NCAA receipt is
    covered in other numbers -- an invoice number, a date, a period, an amount,
    a customer account number -- so this deliberately does not go looking for
    "a number". It finds the label and reads what sits beside it.

    The whole-page pass is tuned for prose and routinely misses a short line of
    small print, so once the label is located the band beside it is read again,
    enlarged and constrained to digits. That second look is what recovers the
    number from a photographed receipt.
    """

    #: The "No" label itself. Recognition renders the colon as ; . or ,
    _NO_LABEL = re.compile(r'^n[o0][;:.,]?$', re.IGNORECASE)
    #: Words that mark a label as belonging to the official receipt number.
    #: Deliberately includes fragments: recognition mangles "Official
    #: Receipt" into things like "Offic al Ree ip!", so matching only the whole
    #: words would miss the very context that identifies the field. "RECE" is
    #: avoided because it also begins "RECEIVED FROM", a different field.
    _RIGHT_CONTEXT = {'OFFICIAL', 'RECEIPT', 'OFFIC', 'RECEIP'}
    #: Words that mark it as belonging to some other numbered field.
    _WRONG_CONTEXT = {
        'INVOICE', 'PERIOD', 'DATE', 'CUSTOMER', 'ACCOUNT', 'REVENUE',
        'CODE', 'TELLER', 'AMOUNT', 'FIGURES', 'WORDS', 'SIGNATURE',
    }

    # Text patterns, used for digital receipts and as a fallback.
    # (pattern, weight). "Invoice" is deliberately absent: on an NCAA receipt
    # that is a different field and must never be taken for the receipt number.
    _PATTERNS = (
        (r'official\s+receipt\s*(?:no\.?|number|#)?\s*[:;.\-]?\s*([A-Za-z0-9][A-Za-z0-9/\-]{3,})', 6),
        (r'receipt\s*(?:no\.?|number|#)\s*[:;.\-]?\s*([A-Za-z0-9][A-Za-z0-9/\-]{3,})', 5),
        (r'\b(NCAA\s*/\s*\d{4}\s*/\s*\d{3,})\b', 4),
        (r'\breceipt\s*[:;\-]\s*([A-Za-z0-9][A-Za-z0-9/\-]{3,})', 4),
        (r'(?:payment|transaction)\s*(?:no\.?|number|id|ref(?:erence)?|#)\s*[:;.\-]?\s*([A-Za-z0-9][A-Za-z0-9/\-]{3,})', 2),
        (r'\bref(?:erence)?\s*(?:no\.?|number)?\s*[:;\-]\s*([A-Za-z0-9][A-Za-z0-9/\-]{3,})', 1),
    )

    def extract_receipt_number(self, ocr_result):
        """Find the Official Receipt Number, or report that it was not read."""
        # Position-aware first: it is the only approach that can tell the
        # receipt number apart from the invoice number sitting below it.
        if getattr(ocr_result, 'words', None) and getattr(ocr_result, 'page', None):
            match = self._from_layout(ocr_result)
            if match is not None and match.found:
                return match

        return self._from_text(ocr_result)

    # -- layout ------------------------------------------------------------
    def _from_layout(self, ocr_result):
        anchors = [
            word for word in ocr_result.words if self._NO_LABEL.match(word.text)
        ]
        if not anchors:
            return None

        scored = sorted(
            ((self._context_score(word, ocr_result.words), word) for word in anchors),
            key=lambda pair: -pair[0],
        )
        best_score, anchor = scored[0]
        if best_score < 0:
            # Every label found belongs to another field -- the invoice
            # number, the period. Reading one of those would be worse than
            # asking the officer to type the receipt number in.
            #
            # A score of zero is accepted: on a poor scan the surrounding
            # words are often too mangled to confirm the context, and the
            # plausibility check on the value itself still rules out the
            # invoice number, dates and amounts.
            return None

        text = ocr_result.page.read_region(
            self._band(anchor, ocr_result.page),
            scale=settings.OCR_FIELD_SCALE,
            # Letters are allowed through: a receipt number may be structured,
            # as in NCAA/2026/004821, and a digits-only read would silently
            # return the last group and drop the rest.
            whitelist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/-: ',
            psm=7,
        )
        value = self._value_from(text)
        if not value:
            return None

        return ReceiptMatch(
            value=value,
            confidence=anchor.confidence,
            needs_review=self._below_threshold(anchor.confidence),
            evidence=_collapse_spaces(text)[:120],
        )

    def _context_score(self, anchor, words):
        """How strongly a "No" label belongs to the official receipt number.

        The surrounding words are run together into one string before being
        searched. Recognition splits words freely -- "Receipt" comes back as
        "Rec" and "eipt" on the sample receipt -- so matching whole tokens
        would miss exactly the context that identifies the field.
        """
        radius = max(anchor.height * 12, 150)
        neighbours = [
            word for word in words
            if word is not anchor
            and abs(word.centre_y - anchor.centre_y) <= anchor.height * 4
            and abs(word.left - anchor.left) <= radius
        ]
        joined = ''.join(
            re.sub(r'[^A-Za-z]', '', word.text).upper() for word in neighbours
        )

        score = 0
        for token in self._RIGHT_CONTEXT:
            if token in joined:
                score += 3
        for token in self._WRONG_CONTEXT:
            if token in joined:
                score -= 4
        return score

    def _band(self, anchor, page):
        """The strip of page immediately to the right of the label."""
        padding = max(int(anchor.height * 0.9), 4)
        return (
            anchor.right - padding // 2,
            anchor.top - padding,
            min(page.size[0], anchor.right + anchor.height * 40),
            anchor.bottom + padding,
        )

    def _value_from(self, text):
        """The receipt number out of a constrained re-read of the field.

        Two shapes occur. A structured reference such as NCAA/2026/004821 is
        taken whole. A plain serial is taken as its longest digit run, which
        also discards the label residue recognition leaves behind -- the
        "NO:" and series letters that precede the number itself.
        """
        cleaned = re.sub(r'\s*([/-])\s*', r'\1', (text or '').upper())

        structured = re.search(r'[A-Z0-9]{2,}(?:/[A-Z0-9]+){1,3}', cleaned)
        if structured and re.search(r'\d', structured.group(0)):
            return structured.group(0).strip('/-')

        runs = [run for run in re.findall(r'\d{4,12}', cleaned)
                if self._is_plausible(run)]
        if runs:
            return max(runs, key=len)
        return ''

    def _is_plausible(self, value):
        digits = re.sub(r'\D', '', value)
        if not 4 <= len(digits) <= 12:
            return False
        if re.fullmatch(r'(19|20)\d{2}', digits):
            return False  # a year, not a receipt number
        return True

    # -- text --------------------------------------------------------------
    def _from_text(self, ocr_result):
        best = None
        for line in ocr_result.lines:
            text = _clean_text(line.text)
            if not text:
                continue
            for pattern, weight in self._PATTERNS:
                found = re.search(pattern, text, re.IGNORECASE)
                if not found:
                    continue
                value = self._normalise(found.group(1))
                if not value or value.upper() in _NAME_STOPWORDS:
                    continue
                if not self._is_plausible(value) and not re.search(r'[A-Za-z]', value):
                    continue
                if best is None or weight > best[0]:
                    best = (weight, value, line.confidence, text)

        if best is None:
            return ReceiptMatch(needs_review=True)

        _, value, confidence, evidence = best
        return ReceiptMatch(
            value=value,
            confidence=confidence,
            needs_review=self._below_threshold(confidence),
            evidence=evidence,
        )

    def _below_threshold(self, confidence):
        return confidence is not None and confidence < settings.OCR_CONFIDENCE_THRESHOLD

    def _normalise(self, value):
        """Tidy a receipt number without guessing at OCR character confusions.

        Whitespace introduced around separators is removed, but characters are
        never substituted: silently turning O into 0 would corrupt a number
        that was actually read correctly.
        """
        value = _clean_text(value).upper()
        value = re.sub(r'\s*([/\-])\s*', r'\1', value)
        value = value.replace(' ', '')
        return value.strip('.,;:-/')
