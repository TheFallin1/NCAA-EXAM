"""Preparing a page image before recognition.

Scanned applications arrive sideways, upside down, and slightly skewed, and a
photograph of a page is often too small for recognition to work well. Feeding
such an image straight to Tesseract produces confident-looking nonsense, so
every page passes through here first:

    crop to the page  ->  find the true rotation  ->  upscale  ->  deskew

Orientation is decided by trying all four rotations on a small, cheap probe and
keeping the one that reads best. Tesseract's own OSD is deliberately not used:
on the scans this system receives it reports a confidence near zero and the
wrong script, and on crisp pages it confidently answers "no rotation" for a
page that is plainly upside down. Measuring how well each orientation actually
reads is slower but it is right.
"""
import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

ROTATIONS = (0, 90, 180, 270)


@dataclass
class Orientation:
    """What was done to a page, for the audit trail and for diagnosis."""

    rotation: int = 0
    skew: float = 0.0
    scale: float = 1.0
    cropped: bool = False
    score: float = 0.0
    upright_score: float = 0.0
    method: str = 'none'

    @property
    def corrected(self):
        return self.rotation != 0 or abs(self.skew) >= 0.1 or self.cropped

    def describe(self):
        parts = []
        if self.rotation:
            parts.append(f'rotated {self.rotation} degrees')
        if abs(self.skew) >= 0.1:
            parts.append(f'deskewed {self.skew:+.1f} degrees')
        if self.cropped:
            parts.append('cropped to the page')
        if self.scale != 1.0:
            parts.append(f'upscaled x{self.scale:.1f}')
        return ', '.join(parts) or 'no correction needed'


def otsu_threshold(histogram):
    """Split a greyscale histogram into ink and paper.

    Otsu's method, computed from the 256-bin histogram Pillow already
    provides. Written out rather than imported so the system needs no
    image-processing library on the NCAA server.
    """
    total = sum(histogram)
    if not total:
        return 128
    weighted_total = sum(value * count for value, count in enumerate(histogram))

    background = 0.0
    background_sum = 0.0
    best_variance = 0.0
    threshold = 128

    for value in range(256):
        background += histogram[value]
        if background == 0:
            continue
        foreground = total - background
        if foreground == 0:
            break
        background_sum += value * histogram[value]
        background_mean = background_sum / background
        foreground_mean = (weighted_total - background_sum) / foreground
        variance = background * foreground * (background_mean - foreground_mean) ** 2
        if variance > best_variance:
            best_variance = variance
            threshold = value

    return threshold


def detect_paper_region(image):
    """Bounding box of the sheet within a photograph, or None.

    Officers photograph documents on a desk, and the dark surround throws off
    page segmentation badly enough that small print stops being read at all.
    Isolating the paper first is what makes a receipt number recoverable.
    """
    from PIL import ImageFilter, ImageOps

    grey = ImageOps.grayscale(image)
    factor = settings.OCR_REGION_WORK_EDGE / max(grey.size)
    if factor < 1:
        small = grey.resize(
            (max(1, int(grey.width * factor)), max(1, int(grey.height * factor)))
        )
    else:
        small = grey

    # Median filtering first, so specks of glare do not enlarge the box.
    small = small.filter(ImageFilter.MedianFilter(5))
    threshold = otsu_threshold(small.histogram())
    box = small.point(lambda value: 255 if value > threshold else 0).getbbox()
    if not box:
        return None

    scale_x = image.width / small.width
    scale_y = image.height / small.height
    left, top, right, bottom = (
        int(box[0] * scale_x), int(box[1] * scale_y),
        int(box[2] * scale_x), int(box[3] * scale_y),
    )

    coverage = ((right - left) * (bottom - top)) / float(image.width * image.height)
    # Too small and the threshold latched onto a highlight; near-total and
    # there was no surround to remove, so cropping would only risk clipping.
    if not settings.OCR_REGION_MIN_COVERAGE <= coverage < 0.98:
        return None

    margin = int(min(image.width, image.height) * 0.01)
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(image.width, right + margin),
        min(image.height, bottom + margin),
    )


def enhance(image):
    """Flatten to high-contrast greyscale for reading small print."""
    from PIL import ImageOps

    return ImageOps.autocontrast(ImageOps.grayscale(image))


def _resample():
    from PIL import Image

    return getattr(Image, 'Resampling', Image).LANCZOS


def upscale(image):
    """Enlarge a small page so recognition has enough pixels to work with.

    A photograph of an A4 page at 1280px is roughly 110 DPI; Tesseract is
    tuned for about 300. Never downscales -- losing detail only hurts.
    """
    target = settings.OCR_MIN_LONG_EDGE
    longest = max(image.width, image.height)
    if longest <= 0 or longest >= target:
        return image, 1.0

    factor = min(target / longest, settings.OCR_MAX_UPSCALE)
    if factor <= 1.01:
        return image, 1.0

    size = (int(image.width * factor), int(image.height * factor))
    return image.resize(size, _resample()), factor


def _rotate(image, degrees):
    """Rotate clockwise by `degrees`. PIL rotates anticlockwise."""
    if degrees % 360 == 0:
        return image
    return image.rotate(-degrees, expand=True)


def _probe(image):
    """A small greyscale copy used only to compare variants.

    Probes are scored, never read for content, so they are made as cheap as
    possible: a page is compared against itself many times during preparation
    and each full-size pass would cost a second or more.
    """
    from PIL import ImageOps

    edge = settings.OCR_ORIENTATION_PROBE_EDGE
    longest = max(image.width, image.height)
    if longest > edge:
        factor = edge / longest
        image = image.resize(
            (max(1, int(image.width * factor)), max(1, int(image.height * factor))),
            _resample(),
        )
    return ImageOps.grayscale(image)


def score_readability(data):
    """How much genuine text a recognition pass found.

    Counting confident, word-shaped results separates a correctly oriented
    page from a rotated one far more sharply than mean confidence alone, which
    stays deceptively high on pages that produced only a handful of fragments.
    """
    good = []
    for text, confidence in zip(data.get('text', []), data.get('conf', [])):
        text = (text or '').strip()
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            continue
        if confidence < 60 or len(text) < 3:
            continue
        if not any(character.isalpha() for character in text):
            continue
        good.append(confidence)

    if not good:
        return 0.0
    # Volume of readable words, tempered by how sure the engine was of them.
    return len(good) * (sum(good) / len(good))


def detect_rotation(image, engine):
    """Find the rotation that makes the page read correctly.

    Returns (degrees clockwise, score of that rotation, score at 0, method).
    """
    probe = _probe(image)

    scores = {}
    for degrees in ROTATIONS:
        scores[degrees] = score_readability(engine.raw_data(_rotate(probe, degrees)))

    best = max(ROTATIONS, key=lambda d: (scores[d], -d))
    upright = scores[0]

    # Only turn the page if the gain is clear. Tesseract reads some rotations
    # perfectly well on its own, so two orientations can both score highly;
    # turning a page that already reads is churn, not a correction.
    if best != 0 and scores[best] < upright * settings.OCR_ROTATION_MARGIN:
        return 0, upright, upright, 'search'

    return best, scores[best], upright, 'search'


def estimate_skew(image, engine):
    """Residual skew in degrees, from the slope of the recognised text lines.

    Word boxes are already produced by recognition, so the tilt of each line
    can be measured from them without pulling in an image-processing library.
    """
    data = engine.raw_data(image)
    lines = {}
    count = len(data.get('text', []))

    for index in range(count):
        text = (data['text'][index] or '').strip()
        if len(text) < 2:
            continue
        try:
            confidence = float(data['conf'][index])
        except (TypeError, ValueError):
            continue
        if confidence < 60:
            continue
        key = (
            data['block_num'][index],
            data['par_num'][index],
            data['line_num'][index],
        )
        centre_x = data['left'][index] + data['width'][index] / 2.0
        centre_y = data['top'][index] + data['height'][index] / 2.0
        lines.setdefault(key, []).append((centre_x, centre_y))

    import math

    angles = []
    for points in lines.values():
        if len(points) < 3:
            continue  # too short to give a reliable slope
        points.sort()
        (x1, y1), (x2, y2) = points[0], points[-1]
        if abs(x2 - x1) < 40:
            continue
        angles.append(math.degrees(math.atan2(y2 - y1, x2 - x1)))

    if len(angles) < 3:
        return 0.0

    angles.sort()
    median = angles[len(angles) // 2]
    if abs(median) > settings.OCR_MAX_SKEW:
        return 0.0  # implausible: a layout artefact rather than a tilted page
    return median


def _deskew(image, degrees):
    """Straighten a page without changing the size of the canvas.

    `expand=True` is deliberately avoided. Growing the canvas moves the page
    geometry, and page segmentation is sensitive enough to that shift to start
    treating a different block as the body of the page -- on a photograph that
    caught a second sheet at another angle, it reads the wrong document
    entirely. A correction of a few degrees about the centre keeps every line
    within the frame regardless.
    """
    from PIL import Image

    # rotate() accepts only NEAREST/BILINEAR/BICUBIC; LANCZOS is resize-only.
    resample = getattr(Image, 'Resampling', Image).BICUBIC
    return image.rotate(degrees, expand=False, resample=resample, fillcolor='white')


def _improves(candidate, current, engine):
    """True when a prepared variant reads better than what it replaces.

    Every correction is checked rather than trusted. Recognition is not
    monotonic in image quality: a step that helps one page can wreck another,
    and a silent regression here surfaces much later as a missing candidate or
    an undetected examination type.
    """
    return (
        score_readability(engine.raw_data(_probe(candidate)))
        > score_readability(engine.raw_data(_probe(current)))
    )


def prepare(image, engine):
    """Return (prepared image, Orientation) ready for recognition."""
    result = Orientation()

    if settings.OCR_CROP_TO_PAGE:
        region = detect_paper_region(image)
        if region:
            # Not readability-checked: the decision is geometric, and a
            # sideways page reads as nothing at every stage, so a comparison
            # here would reject exactly the crop such a page depends on.
            image = image.crop(region)
            result.cropped = True

    if not settings.OCR_AUTO_ROTATE:
        prepared, result.scale = upscale(image)
        return prepared, result

    rotation, score, upright, method = detect_rotation(image, engine)
    result.rotation = rotation
    result.score = score
    result.upright_score = upright
    result.method = method

    prepared = _rotate(image, rotation)
    prepared, result.scale = upscale(prepared)

    if settings.OCR_DESKEW:
        skew = estimate_skew(_probe(prepared), engine)
        if abs(skew) >= settings.OCR_MIN_SKEW:
            straightened = _deskew(prepared, skew)
            # Straightening is kept only if it genuinely reads better. A page
            # can carry a second sheet, a stamp or marginalia at another
            # angle, which drags the measured skew away from the body text;
            # applying that would tilt a page that was already straight.
            if _improves(straightened, prepared, engine):
                prepared = straightened
                result.skew = skew
            else:
                logger.debug(
                    'Discarded a %.1f degree skew correction that read worse', skew
                )

    if result.corrected:
        logger.info('Page prepared: %s', result.describe())
    return prepared, result
