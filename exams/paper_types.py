"""The paper types offered under each examination category.

Two things live here: the catalogue that drives the dependent Paper Type
dropdown, and the detection that reads a paper out of an application letter.

The catalogue is *configuration*, not code. `PaperType` rows in the database
decide which papers exist, what they are called and how they may be written in
a letter, so NCAA can add a paper or replace the placeholder AME names from the
admin without a code or schema change. `DEFAULT_PAPER_TYPES` below only seeds
that table the first time.

Detection follows the same rule the examination-category detection follows: a
term is believed when it appears in an examination context, not merely
somewhere on the page. "B737" in a letterhead, a fleet list or a training
history says nothing about which examination is being applied for; "B737
examination" does. Where the evidence does not single out one paper, nothing is
returned -- guessing would schedule a candidate for the wrong paper.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from .models import ExamCategory, PaperType

# ---------------------------------------------------------------------------
# Seed catalogue
# ---------------------------------------------------------------------------
# (code, name, detection terms). Applied once by a data migration; after that
# the database rows are the authority and this is only a record of the starting
# point. The AME papers beyond the general paper are placeholders -- NCAA has
# not confirmed their official names -- and are meant to be renamed in the
# admin, which is why nothing anywhere keys off their names.
DEFAULT_PAPER_TYPES = {
    ExamCategory.CABIN_CREW: [
        ('b737', 'B737', ['B737', 'B-737', 'B 737', 'Boeing 737', '737']),
        ('general', 'General Paper', ['General Paper', 'General Examination']),
    ],
    ExamCategory.PILOT: [
        ('general', 'General Paper', ['General Paper', 'General Examination']),
    ],
    ExamCategory.FLIGHT_DISPATCH: [
        ('paper_1', 'Paper 1', ['Paper 1', 'Paper I', 'Paper One', 'Paper-1']),
        ('paper_2', 'Paper 2', ['Paper 2', 'Paper II', 'Paper Two', 'Paper-2']),
    ],
    ExamCategory.AME: [
        ('general', 'General Paper', ['General Paper', 'General Examination']),
        # Placeholder names, pending the official NCAA titles.
        ('ame_paper_2', 'AME Paper 2', ['AME Paper 2', 'Paper 2', 'Paper II']),
        ('ame_paper_3', 'AME Paper 3', ['AME Paper 3', 'Paper 3', 'Paper III']),
    ],
}


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def papers_for(exam_category, include_inactive=False):
    """The configured papers for one category, in dropdown order."""
    if not exam_category:
        return []
    queryset = PaperType.objects.filter(exam_category=exam_category)
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return list(queryset)


def choices_for(exam_category):
    """(code, name) pairs for one category, for a form field."""
    return [(paper.code, paper.name) for paper in papers_for(exam_category)]


def all_choices():
    """Every active (code, name) pair across every category.

    The Paper Type field is validated against this so a posted value is a real
    paper; whether it belongs to the chosen category is a separate check, which
    is what produces the "invalid combination" error rather than a bare
    "not a valid choice".
    """
    seen, choices = set(), []
    for paper in PaperType.objects.filter(is_active=True):
        if paper.code in seen:
            continue
        seen.add(paper.code)
        choices.append((paper.code, paper.name))
    return choices


def catalogue():
    """{category value: [{'value': code, 'label': name}, ...]}.

    Serialised into the intake page so the Paper Type dropdown can repopulate
    itself the moment the category changes, with no round trip.
    """
    grouped = {value: [] for value, _ in ExamCategory.choices}
    for paper in PaperType.objects.filter(is_active=True):
        grouped.setdefault(paper.exam_category, []).append(
            {'value': paper.code, 'label': paper.name}
        )
    return grouped


def get(exam_category, code):
    """One configured paper, or None."""
    if not (exam_category and code):
        return None
    return PaperType.objects.filter(exam_category=exam_category, code=code).first()


def is_valid(exam_category, code):
    """True when this paper is offered under this category and still active.

    The rule behind "Cabin Crew + Paper 1 must not be accepted": the pair is
    checked, never the paper on its own.
    """
    paper = get(exam_category, code)
    return paper is not None and paper.is_active


def label_for(exam_category, code):
    """The configured name for a stored code.

    Falls back to a readable form of the code itself so a paper retired or
    renamed out of the catalogue never leaves a record showing a blank.
    """
    if not code:
        return ''
    paper = get(exam_category, code)
    if paper is not None:
        return paper.name
    return str(code).replace('_', ' ').title()


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------
# Words that mark surrounding text as being about the examination itself.
_CONTEXT_WORDS = r'exam(?:ination|inations|s)?|papers?|sitting|write'

# How many words may sit between a term and the word that gives it context, so
# "examination for the B737" reads while "Boeing 737 Classic Type rating exam"
# -- an aside about a type rating, not the paper applied for -- does not. Kept
# to the same two words the examination-category detection allows.
_GAP = r'(?:\s+[\w/&-]+){0,2}\s+'

# Weights mirror the examination-category detection: a term named in an
# examination context outranks any number of bare mentions, and the heading
# outranks the body.
_CONTEXT_WEIGHT = 10
_MENTION_WEIGHT = 1
_HEADING_CHARS = 600
_HEADING_WEIGHT = 3


@dataclass
class PaperDetection:
    """Outcome of scanning an application letter for its paper type."""

    paper_type: str = None
    scores: dict = field(default_factory=dict)
    evidence: str = ''
    #: More than one paper was named with equal weight. Never resolved
    #: automatically -- the officer is asked instead.
    ambiguous: bool = False
    #: The paper was named in an examination context rather than in passing.
    contextual: bool = False

    @property
    def detected(self):
        return self.paper_type is not None


def normalize_text(value):
    """Flatten OCR text so a phrase broken across lines still matches."""
    if not value:
        return ''
    text = unicodedata.normalize('NFKC', str(value))
    text = text.replace('–', '-').replace('—', '-')
    return re.sub(r'\s+', ' ', text).strip()


def _term_pattern(term):
    """A regex for one configured term, tolerant of OCR spacing.

    "B737" is written B737, B-737 and B 737 by different training schools and
    recognition adds spaces of its own, so the separators inside a term are
    matched loosely rather than literally.
    """
    parts = [re.escape(part) for part in re.split(r'[\s/-]+', term.strip()) if part]
    if not parts:
        return None
    return r'\s*[-/]?\s*'.join(parts)


def _is_self_contextual(term):
    """True when the term already states that it is an examination or paper.

    "General Paper" and "Paper 1" name the examination on their own. A bare
    model number such as "B737" does not, and must be found next to
    examination wording before it counts.
    """
    return re.search(r'\b(?:paper|exam|examination)\b', term, re.IGNORECASE) is not None


def _compile(paper):
    """(context patterns, mention patterns) for one configured paper."""
    contexts, mentions = [], []
    for term in paper.terms:
        pattern = _term_pattern(term)
        if not pattern:
            continue
        mentions.append(re.compile(r'\b(?:' + pattern + r')\b', re.IGNORECASE))
        if _is_self_contextual(term):
            contexts.append(re.compile(r'\b(?:' + pattern + r')\b', re.IGNORECASE))
            continue
        contexts.append(
            re.compile(
                r'\b(?:' + pattern + r')\b' + _GAP + r'(?:' + _CONTEXT_WORDS + r')\b'
                r'|(?:' + _CONTEXT_WORDS + r')\b' + _GAP + r'(?:' + pattern + r')\b',
                re.IGNORECASE,
            )
        )
    return contexts, mentions


def _scan(text, patterns_by_paper, weight, heading_length):
    """Accumulate (scores, evidence, first position) over one tier."""
    scores, evidence, first_seen = {}, {}, {}
    for code, patterns in patterns_by_paper.items():
        for pattern in patterns:
            for match in pattern.finditer(text):
                bonus = _HEADING_WEIGHT if match.start() < heading_length else 1
                scores[code] = scores.get(code, 0) + weight * bonus
                evidence.setdefault(code, match.group(0).strip())
                position = first_seen.get(code)
                if position is None or match.start() < position:
                    first_seen[code] = match.start()
    return scores, evidence, first_seen


def detect(text, exam_category):
    """Read the paper type out of an application letter.

    Only the papers configured for `exam_category` are considered: the paper
    vocabulary is category-scoped ("Paper 1" means one thing under Flight
    Dispatch and another under AME), and the category has already been detected
    and matched by the time this runs.

    Returns a PaperDetection whose `paper_type` is None when the letter does
    not say. That is a real answer, not a failure -- the officer is asked to
    verify rather than being handed a guess.
    """
    detection = PaperDetection()
    if not text or not text.strip() or not exam_category:
        return detection

    papers = papers_for(exam_category)
    if not papers:
        return detection

    context_patterns, mention_patterns = {}, {}
    for paper in papers:
        contexts, mentions = _compile(paper)
        if contexts:
            context_patterns[paper.code] = contexts
        if mentions:
            mention_patterns[paper.code] = mentions

    flat = normalize_text(text)
    heading_length = min(_HEADING_CHARS, len(flat))

    scores, evidence, first_seen = _scan(
        flat, context_patterns, _CONTEXT_WEIGHT, heading_length
    )
    if scores:
        detection.contextual = True
    else:
        # No paper is named in an examination context. Bare mentions are far
        # too weak to schedule on -- a fleet list names every aircraft type the
        # school owns -- so they are recorded but never resolved to a paper.
        detection.scores = _scan(
            flat, mention_patterns, _MENTION_WEIGHT, heading_length
        )[0]
        return detection

    detection.scores = scores
    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], first_seen.get(item[0], 10 ** 9), item[0]),
    )
    # A tie between two papers is genuine ambiguity: a letter that names both
    # with equal weight says nothing about which one to schedule.
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        detection.ambiguous = True
        return detection

    detection.paper_type = ranked[0][0]
    detection.evidence = evidence.get(detection.paper_type, '')
    detection.ambiguous = len(scores) > 1
    return detection


def matches(officer_value, detected_value):
    """True when the officer's paper and the detected paper are the same."""
    officer = (officer_value or '').strip()
    detected = (detected_value or '').strip()
    return bool(officer) and officer == detected
