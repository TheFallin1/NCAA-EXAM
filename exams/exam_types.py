"""Centralised examination-type vocabulary.

The officer's dropdown selection and the examination type detected by OCR are
both resolved through this module, so the two values compared in the mandatory
match check are always expressed in the same canonical terms.

Detection is deliberately context-aware rather than a keyword search. A letter
mentions aviation vocabulary all over the place -- "Boeing 737 Classic Type
rating exam", "Air - Law" -- and none of that says what examination is being
applied for. What does say it is the phrasing around the type:

    REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS
    APPLICATION FOR PILOT EXAMINATION
    ... the just concluded Cabin crew ab-initio training

So a type named inside an examination context always outranks a type merely
mentioned somewhere on the page. Matching stays pattern-driven, never fuzzy:
accepting a near-miss would mean scheduling a candidate for the wrong
examination category.
"""
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field

from .models import ExamType

# Papers only apply to Flight Dispatch; every other type is a single sitting.
FLIGHT_DISPATCH_PAPERS = ('paper_1', 'paper_2')


def has_papers(exam_type):
    """True when the examination type is split across multiple papers."""
    return exam_type == ExamType.FLIGHT_DISPATCH


# How each type may be written. Ordered most specific first so that
# "flight dispatch" is never reduced to "flight".
_TERMS = OrderedDict((
    (ExamType.FLIGHT_DISPATCH, r'flight\s*dispatch(?:er|ers|ing)?'),
    (ExamType.CABIN_CREW, r'cabin\s*crew|cabin\s*attendants?'),
    (ExamType.AME, (
        r'aircraft\s+maintenance\s+engineer(?:ing|s)?'
        r'|aircraft\s+maintenance\s+licen[cs]e'
        # Abbreviations stay case-sensitive via the scoped (?-i:) flag, even
        # though the surrounding pattern ignores case: a lower-case "ame" is
        # far more likely to be OCR noise than an examination type.
        r'|(?-i:A\.M\.E\.?|AME)'
    )),
    (ExamType.PILOT, r'pilots?|(?-i:PPL|CPL|ATPL)'),
))

# Up to two words may sit between the type and the word that gives it context,
# which is what lets "CABIN CREW AB-INITIO STUDENTS" read as a cabin crew
# context rather than a bare mention.
_GAP = r'(?:\s+[\w-]+){0,2}\s+'

# Phrasing that marks a type as the subject of the application. `{term}` is
# substituted with the alternation for each examination type.
_CONTEXT_TEMPLATES = (
    r'request\s+for\s+(?:an?\s+)?exam(?:ination)?\s+date\s+for\s+(?:the\s+)?(?:{term})',
    r'exam(?:ination)?\s+date\s+for\s+(?:the\s+)?(?:{term})',
    r'application\s+for\s+(?:the\s+)?(?:{term})',
    r'apply(?:ing)?\s+for\s+(?:the\s+)?(?:{term})',
    r'request\s+for\s+(?:the\s+)?(?:{term})',
    r'exam(?:ination)?\s+for\s+(?:the\s+)?(?:{term})',
    r'schedule\s+(?:the\s+)?(?:{term})',
    r'(?:{term})' + _GAP + r'exam(?:ination|s)?\b',
    r'(?:{term})' + _GAP + r'(?:students?|candidates?|trainees?|applicants?|personnel)\b',
    r'(?:{term})' + _GAP + r'(?:training|course)\b',
    r'(?:{term})' + _GAP + r'licen[cs]e',
)

# Extra spellings accepted when normalising a single known value (as opposed to
# scanning free text). Keys must already be lower case and space-collapsed.
_ALIASES = {
    'cabin crew': ExamType.CABIN_CREW,
    'cabincrew': ExamType.CABIN_CREW,
    'cabin attendant': ExamType.CABIN_CREW,
    'cabin crew ab-initio': ExamType.CABIN_CREW,
    'cabin crew ab initio': ExamType.CABIN_CREW,
    'ame': ExamType.AME,
    'a.m.e': ExamType.AME,
    'a.m.e.': ExamType.AME,
    'aircraft maintenance engineering': ExamType.AME,
    'aircraft maintenance engineer': ExamType.AME,
    'pilot': ExamType.PILOT,
    'pilots': ExamType.PILOT,
    'flight dispatch': ExamType.FLIGHT_DISPATCH,
    'flightdispatch': ExamType.FLIGHT_DISPATCH,
    'flight dispatcher': ExamType.FLIGHT_DISPATCH,
    'flight_dispatch': ExamType.FLIGHT_DISPATCH,
}

# How far into the document counts as the heading, where the examination type
# is normally stated. Matches here outrank passing mentions further down.
_HEADING_CHARS = 600
_HEADING_WEIGHT = 3

# A type named in an examination context outweighs any number of bare mentions.
_CONTEXT_WEIGHT = 10
_MENTION_WEIGHT = 1


def _compile_contexts():
    compiled = OrderedDict()
    for exam_type, term in _TERMS.items():
        # Plain substitution, not str.format: the templates contain regex
        # repetition counts like {0,2} that format() would read as fields.
        compiled[exam_type] = [
            re.compile(template.replace('{term}', term), re.IGNORECASE)
            for template in _CONTEXT_TEMPLATES
        ]
    return compiled


def _compile_mentions():
    compiled = OrderedDict()
    for exam_type, term in _TERMS.items():
        compiled[exam_type] = re.compile(rf'\b(?:{term})\b', re.IGNORECASE)
    return compiled


_CONTEXT_PATTERNS = _compile_contexts()
_MENTION_PATTERNS = _compile_mentions()


def _collapse(value):
    """Lower-case, strip accents, and collapse runs of whitespace."""
    if value is None:
        return ''
    text = unicodedata.normalize('NFKD', str(value))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', text).strip().lower()


def normalize_text(value):
    """Flatten OCR text so phrases split across lines still match.

    Recognition breaks a heading wherever the page does, so "REQUEST FOR EXAM
    DATE FOR CABIN\\nCREW STUDENTS" is common. Collapsing the whitespace lets
    one pattern cover both.
    """
    if not value:
        return ''
    text = unicodedata.normalize('NFKC', str(value))
    text = text.replace('–', '-').replace('—', '-')
    return re.sub(r'\s+', ' ', text).strip()


def normalize(value):
    """Resolve a single value to a canonical ExamType, or None.

    Accepts the stored value ("flight_dispatch"), the human label
    ("Flight Dispatch"), and the common spellings officers and letters use.
    """
    collapsed = _collapse(value)
    if not collapsed:
        return None

    for choice in ExamType:
        if collapsed == choice.value.lower() or collapsed == choice.label.lower():
            return choice.value

    alias = _ALIASES.get(collapsed)
    if alias is not None:
        return alias

    # Fall back to term matching so "PILOT EXAMINATION" resolves cleanly.
    for exam_type, pattern in _MENTION_PATTERNS.items():
        if pattern.search(collapsed):
            return exam_type
    return None


def label_for(exam_type):
    """Human-readable label for a canonical value, for display and messages."""
    for choice in ExamType:
        if choice.value == exam_type:
            return choice.label
    return str(exam_type or '').replace('_', ' ').title() or 'Unknown'


@dataclass
class ExamTypeDetection:
    """Outcome of scanning an application letter for its examination type."""

    exam_type: str = None
    scores: dict = field(default_factory=dict)
    evidence: str = ''
    ambiguous: bool = False
    #: True when the type was named inside an examination context rather than
    #: merely mentioned somewhere on the page.
    contextual: bool = False

    @property
    def detected(self):
        return self.exam_type is not None

    @property
    def matched_types(self):
        return sorted(self.scores)

    @property
    def label(self):
        return label_for(self.exam_type) if self.exam_type else ''


def _scan(text, patterns, weight, heading_length, case_sensitive=False):
    """Accumulate (scores, evidence, first position) for one tier."""
    scores, evidence, first_seen = {}, {}, {}

    for exam_type, compiled in patterns.items():
        for pattern in (compiled if isinstance(compiled, list) else [compiled]):
            for match in pattern.finditer(text):
                bonus = _HEADING_WEIGHT if match.start() < heading_length else 1
                scores[exam_type] = scores.get(exam_type, 0) + weight * bonus
                evidence.setdefault(exam_type, match.group(0).strip())
                position = first_seen.get(exam_type)
                if position is None or match.start() < position:
                    first_seen[exam_type] = match.start()

    return scores, evidence, first_seen


def detect(text):
    """Scan free OCR text and report which examination type it describes.

    Returns an ExamTypeDetection. `ambiguous` is set when more than one
    examination category is named at the same level of evidence, which always
    sends the application to officer review rather than being resolved
    automatically.
    """
    detection = ExamTypeDetection()
    if not text or not text.strip():
        return detection

    flat = normalize_text(text)
    heading_length = min(_HEADING_CHARS, len(flat))

    context_scores, context_evidence, context_first = _scan(
        flat, _CONTEXT_PATTERNS, _CONTEXT_WEIGHT, heading_length
    )

    if context_scores:
        # An explicit examination context settles it; bare mentions of other
        # types elsewhere in the letter are noise and are not even considered.
        scores, evidence, first_seen = context_scores, context_evidence, context_first
        detection.contextual = True
    else:
        scores, evidence, first_seen = _scan(
            flat, _MENTION_PATTERNS, _MENTION_WEIGHT, heading_length
        )

    if not scores:
        return detection

    # Rank by weight, then by whichever type the letter names first. A letter
    # headed "PILOT EXAMINATION" that mentions cabin crew further down is a
    # pilot letter; falling back to alphabetical order here would block it as a
    # mismatch against the wrong type.
    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], first_seen.get(item[0], 10 ** 9), item[0]),
    )
    detection.exam_type = ranked[0][0]
    detection.scores = scores
    detection.evidence = evidence.get(detection.exam_type, '')
    detection.ambiguous = len(scores) > 1
    return detection


def matches(officer_value, detected_value):
    """True when the officer's selection and the OCR detection agree."""
    officer = normalize(officer_value)
    detected = normalize(detected_value)
    return officer is not None and officer == detected
