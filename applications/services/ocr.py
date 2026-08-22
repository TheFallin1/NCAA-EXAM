"""Self-hosted OCR.

Every engine here runs on the NCAA server. No document, or any part of one, is
sent to an external service.

The rest of the application talks to `read_document()` and the `OCRResult` it
returns, so the underlying engine can be replaced without touching callers.
"""
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from django.conf import settings

logger = logging.getLogger(__name__)

# Text-layer confidence. A digital PDF carries its characters exactly, so there
# is no recognition uncertainty to report.
TEXT_LAYER_CONFIDENCE = 100.0


class OCRError(Exception):
    """Raised when a document cannot be read at all."""


class OCRUnavailableError(OCRError):
    """Raised when the configured engine is not installed on this server."""


@dataclass
class OCRLine:
    """One line of recognised text with the engine's confidence in it."""

    text: str
    confidence: float = None
    page: int = 1


@dataclass
class OCRWord:
    """One recognised word and where it sits on the prepared page.

    Position is what lets a field be found by its label rather than by
    guessing at the text: "the number to the right of Official Receipt No".
    """

    text: str
    confidence: float = None
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0
    page: int = 1

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height

    @property
    def centre_y(self):
        return self.top + self.height / 2.0


class OCRPage:
    """The prepared image, kept so a region can be re-read at higher detail.

    A whole-page pass is tuned for prose and routinely misses a short line of
    small print. Reading just the band beside a field label, enlarged and
    flattened to high contrast, recovers it.
    """

    def __init__(self, image, engine):
        self.image = image
        self.engine = engine

    @property
    def size(self):
        return self.image.size

    def read_region(self, box, scale=6, whitelist=None, psm=7):
        from .preprocess import enhance

        left, top, right, bottom = box
        left = max(0, int(left))
        top = max(0, int(top))
        right = min(self.image.width, int(right))
        bottom = min(self.image.height, int(bottom))
        if right - left < 4 or bottom - top < 4:
            return ''

        region = self.image.crop((left, top, right, bottom))
        if scale > 1:
            resample = _pil_resample()
            region = region.resize(
                (region.width * scale, region.height * scale), resample
            )
        return self.engine.raw_text(enhance(region), psm=psm, whitelist=whitelist)


def _pil_resample():
    from PIL import Image

    return getattr(Image, 'Resampling', Image).LANCZOS


@dataclass
class OCRResult:
    lines: list = field(default_factory=list)
    page_count: int = 0
    engine: str = ''
    used_text_layer: bool = False
    duration_ms: int = 0
    #: What page preparation had to do, for the audit trail.
    rotation: int = 0
    skew: float = 0.0
    #: Word positions, and a handle to re-read part of the prepared page.
    words: list = field(default_factory=list)
    page: object = None

    @property
    def text(self):
        return '\n'.join(line.text for line in self.lines)

    @property
    def mean_confidence(self):
        scores = [
            line.confidence
            for line in self.lines
            if line.confidence is not None and line.text.strip()
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)

    @property
    def is_empty(self):
        return not self.text.strip()


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------
class OCREngine(ABC):
    name = 'abstract'

    @abstractmethod
    def raw_data(self, image):
        """Recognise an image and return word-level results.

        A mapping with the pytesseract column names: text, conf, block_num,
        par_num, line_num, left, top, width, height. Page preparation needs
        this detail to compare orientations and measure skew.
        """

    def image_to_lines(self, image, page=1):
        """Recognise a PIL image and return a list of OCRLine."""
        return _group_words_into_lines(self.raw_data(image), page)

    def raw_text(self, image, psm=None, whitelist=None):
        """Recognise an image as plain text, optionally constrained.

        Used for re-reading a single field, where telling the engine to expect
        one line of digits markedly improves the result.
        """
        return '\n'.join(line.text for line in self.image_to_lines(image))

    def check_available(self):
        """Raise OCRUnavailableError if this engine cannot run."""
        return True


class TesseractEngine(OCREngine):
    """Tesseract 5 via pytesseract.

    Chosen for on-premise use because it installs from the OS package manager
    with no model download at first run, needs no GPU, and reports per-word
    confidence, which the officer review screen relies on.
    """

    name = 'tesseract'

    def _pytesseract(self):
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise OCRUnavailableError(
                'pytesseract is not installed on this server.'
            ) from exc
        if settings.OCR_ENGINE_PATH:
            pytesseract.pytesseract.tesseract_cmd = settings.OCR_ENGINE_PATH
        return pytesseract

    def check_available(self):
        pytesseract = self._pytesseract()
        try:
            pytesseract.get_tesseract_version()
        except Exception as exc:
            raise OCRUnavailableError(
                'The Tesseract OCR engine could not be started. Check that it '
                'is installed and that OCR_ENGINE_PATH points at the binary.'
            ) from exc
        return True

    def raw_text(self, image, psm=None, whitelist=None):
        pytesseract = self._pytesseract()

        options = []
        if psm:
            options.append(f'--psm {psm}')
        if whitelist:
            options.append(f'-c tessedit_char_whitelist={whitelist}')

        try:
            return pytesseract.image_to_string(
                image,
                lang=settings.OCR_LANGUAGES,
                config=' '.join(options),
                timeout=settings.OCR_TIMEOUT_SECONDS,
            )
        except Exception:
            # A failed field re-read is not fatal; the caller falls back.
            return ''

    def raw_data(self, image):
        pytesseract = self._pytesseract()
        from pytesseract import Output

        try:
            return pytesseract.image_to_data(
                image,
                lang=settings.OCR_LANGUAGES,
                output_type=Output.DICT,
                timeout=settings.OCR_TIMEOUT_SECONDS,
            )
        except OCRUnavailableError:
            raise
        except Exception as exc:
            raise OCRError(f'Tesseract failed to read the page: {exc}') from exc


class FakeEngine(OCREngine):
    """Deterministic stand-in used by the test suite.

    Lets the whole workflow be exercised on a machine that has no Tesseract
    installed, and makes extraction tests reproducible.
    """

    name = 'fake'

    #: Text keyed by document kind ('letter' / 'receipt'), set by tests.
    responses = {}
    #: Used when no keyed response matches.
    default_text = ''
    #: When set, every call raises this error instead.
    raise_error = None

    @classmethod
    def reset(cls):
        cls.responses = {}
        cls.default_text = ''
        cls.raise_error = None

    def raw_data(self, image):
        """A pytesseract-shaped result built from the configured text."""
        if type(self).raise_error is not None:
            raise type(self).raise_error

        text = type(self).responses.get(None, type(self).default_text)
        data = {
            key: []
            for key in ('text', 'conf', 'block_num', 'par_num', 'line_num',
                        'left', 'top', 'width', 'height')
        }
        for line_number, line in enumerate(text.splitlines(), start=1):
            left = 0
            for word in line.split():
                data['text'].append(word)
                data['conf'].append(TEXT_LAYER_CONFIDENCE)
                data['block_num'].append(1)
                data['par_num'].append(1)
                data['line_num'].append(line_number)
                data['left'].append(left)
                data['top'].append(line_number * 20)
                data['width'].append(len(word) * 10)
                data['height'].append(14)
                left += len(word) * 10 + 8
        return data

    def image_to_lines(self, image, page=1):
        return self._lines_for(None, page)

    def _lines_for(self, hint, page=1):
        if type(self).raise_error is not None:
            raise type(self).raise_error
        text = type(self).responses.get(hint, type(self).default_text)
        return [
            OCRLine(text=line, confidence=TEXT_LAYER_CONFIDENCE, page=page)
            for line in text.splitlines()
        ]


_ENGINES = {
    TesseractEngine.name: TesseractEngine,
    FakeEngine.name: FakeEngine,
}


def get_engine(name=None):
    """Instantiate the configured OCR engine."""
    name = (name or settings.OCR_ENGINE or '').strip().lower()
    engine_class = _ENGINES.get(name)
    if engine_class is None:
        raise OCRUnavailableError(
            f'Unknown OCR engine "{name}". Configure OCR_ENGINE as one of: '
            f'{", ".join(sorted(_ENGINES))}.'
        )
    return engine_class()


def words_from_data(data, page=1):
    """Word-level results with their positions on the page."""
    words = []
    for index in range(len(data.get('text', []))):
        text = (data['text'][index] or '').strip()
        if not text:
            continue
        try:
            confidence = float(data['conf'][index])
        except (TypeError, ValueError):
            confidence = -1.0
        words.append(OCRWord(
            text=text,
            confidence=confidence if confidence >= 0 else None,
            left=int(data['left'][index]),
            top=int(data['top'][index]),
            width=int(data['width'][index]),
            height=int(data['height'][index]),
            page=page,
        ))
    return words


def _group_words_into_lines(data, page):
    """Fold pytesseract's word-level output into lines with mean confidence."""
    lines = {}
    count = len(data.get('text', []))
    for index in range(count):
        word = (data['text'][index] or '').strip()
        if not word:
            continue
        try:
            confidence = float(data['conf'][index])
        except (TypeError, ValueError):
            confidence = -1.0
        key = (
            data['block_num'][index],
            data['par_num'][index],
            data['line_num'][index],
        )
        entry = lines.setdefault(key, {'words': [], 'scores': []})
        entry['words'].append(word)
        # Tesseract reports -1 for entries it did not score.
        if confidence >= 0:
            entry['scores'].append(confidence)

    result = []
    for key in sorted(lines):
        entry = lines[key]
        scores = entry['scores']
        result.append(
            OCRLine(
                text=' '.join(entry['words']),
                confidence=(sum(scores) / len(scores)) if scores else None,
                page=page,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Document reading
# ---------------------------------------------------------------------------
def read_document(path, engine=None, hint=None):
    """Read a PDF or image file and return an OCRResult.

    PDFs are checked for an embedded text layer first. Scanners increasingly
    emit searchable PDFs, and a letter produced digitally always has one --
    reading it directly is both exact and far faster than rasterising.
    """
    engine = engine or get_engine()
    started = time.monotonic()

    extension = os.path.splitext(path)[1].lower().lstrip('.')
    if extension == 'pdf':
        result = _read_pdf(path, engine, hint)
    else:
        result = _read_image(path, engine, hint)

    result.engine = engine.name
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result


def _read_image(path, engine, hint=None):
    if isinstance(engine, FakeEngine):
        lines = engine._lines_for(hint, page=1)
        return OCRResult(lines=lines, page_count=1)

    engine.check_available()
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise OCRUnavailableError('Pillow is not installed on this server.') from exc

    from .preprocess import prepare

    try:
        with Image.open(path) as image:
            image.load()
            prepared, orientation = prepare(image, engine)
            # prepare() may hand back the very object the context manager is
            # about to close, so keep an independent copy.
            prepared = prepared.copy()
        data = engine.raw_data(prepared)
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(
            'The image could not be opened. It may be corrupted -- '
            f'please rescan it. ({exc})'
        ) from exc

    return OCRResult(
        lines=_group_words_into_lines(data, 1),
        page_count=1,
        rotation=orientation.rotation,
        skew=orientation.skew,
        words=words_from_data(data, 1),
        page=OCRPage(prepared, engine),
    )


def _read_pdf(path, engine, hint=None):
    if isinstance(engine, FakeEngine):
        lines = engine._lines_for(hint, page=1)
        return OCRResult(lines=lines, page_count=1)

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise OCRUnavailableError(
            'pypdfium2 is not installed on this server, so PDF documents '
            'cannot be read.'
        ) from exc

    try:
        document = pdfium.PdfDocument(path)
    except Exception as exc:
        raise OCRError(
            'The PDF could not be opened. It may be corrupted or password '
            f'protected -- please rescan it. ({exc})'
        ) from exc

    try:
        page_count = min(len(document), settings.OCR_MAX_PAGES)
        if page_count == 0:
            raise OCRError('The PDF contains no pages.')

        text_lines = _pdf_text_layer(document, page_count)
        if text_lines is not None:
            return OCRResult(
                lines=text_lines, page_count=page_count, used_text_layer=True
            )

        engine.check_available()
        from .preprocess import prepare

        scale = settings.OCR_DPI / 72.0
        lines = []
        words = []
        first_page = None
        rotation = 0
        skew = 0.0
        for index in range(page_count):
            page = document[index]
            try:
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
            except Exception as exc:
                raise OCRError(
                    f'Page {index + 1} of the PDF could not be rendered: {exc}'
                ) from exc
            # Pages are prepared individually: a stack fed through a scanner
            # can easily come out with one sheet the wrong way round.
            prepared, orientation = prepare(image, engine)
            if index == 0:
                rotation, skew = orientation.rotation, orientation.skew
                first_page = OCRPage(prepared, engine)
            data = engine.raw_data(prepared)
            lines.extend(_group_words_into_lines(data, index + 1))
            words.extend(words_from_data(data, index + 1))
        return OCRResult(
            lines=lines,
            page_count=page_count,
            rotation=rotation,
            skew=skew,
            words=words,
            page=first_page,
        )
    finally:
        try:
            document.close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


def _pdf_text_layer(document, page_count):
    """Return embedded-text lines, or None if the PDF is a plain scan."""
    lines = []
    total_characters = 0
    for index in range(page_count):
        try:
            page = document[index]
            textpage = page.get_textpage()
            text = textpage.get_text_range() or ''
        except Exception:
            return None
        total_characters += len(text.strip())
        for raw_line in text.splitlines():
            lines.append(
                OCRLine(
                    text=raw_line.strip(),
                    confidence=TEXT_LAYER_CONFIDENCE,
                    page=index + 1,
                )
            )

    if total_characters < settings.OCR_PDF_TEXT_LAYER_MIN_CHARS:
        return None
    return [line for line in lines if line.text]
