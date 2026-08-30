"""ReportLab PDF slip generator (works on Windows without GTK)."""
import base64
import io

from django.conf import settings
from django.contrib.staticfiles import finders
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from exams.models import ExamSchedule

from .utils import generate_qr_base64

NAVY = colors.HexColor('#1A1B5D')
RULE = colors.HexColor('#DDE1E4')


def _document(buffer):
    return SimpleDocTemplate(
        buffer,
        pagesize=A5,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        'NCAATitle', parent=styles['Heading2'], textColor=NAVY,
        fontSize=11, alignment=1, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        'NCAASub', parent=styles['Normal'], fontSize=8,
        textColor=colors.grey, alignment=1, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        'Banner', parent=styles['Heading3'], textColor=colors.white,
        fontSize=10, alignment=1,
    ))
    styles.add(ParagraphStyle(
        'PaperTitle', parent=styles['Normal'], textColor=NAVY,
        fontSize=9, spaceAfter=2, fontName='Helvetica-Bold',
    ))
    return styles


def _slip_context(exam, request):
    from .utils import get_slip_context

    if request is not None:
        return get_slip_context(exam, request)

    from django.utils import timezone

    return {
        'generated_at': timezone.localtime(timezone.now()),
        'officer_username': exam.scheduled_by.username,
    }


def _value(value, fallback='To be advised'):
    return str(value) if value not in (None, '') else fallback


def _slip_elements(exam, doc, styles, context):
    """Flowables for one examination slip."""
    generated_at = context.get('generated_at')
    officer_username = context.get('officer_username', exam.scheduled_by.username)

    elements = []

    logo_path = finders.find('images/ncaa_logo.png')
    if logo_path:
        try:
            logo = Image(logo_path, width=22 * mm, height=22 * mm)
            logo.hAlign = 'CENTER'
            elements.append(logo)
            elements.append(Spacer(1, 4 * mm))
        except Exception:
            pass

    elements.append(Paragraph(settings.NCAA_FULL_NAME.upper(), styles['NCAATitle']))
    elements.append(
        Paragraph('Aviation Examination Scheduling System', styles['NCAASub'])
    )

    banner_text = 'EXAMINATION SLIP'
    # `has_papers` is true only for records written under the old model, where
    # one examination covered several papers. Everything issued now names the
    # single paper it is for, in the detail table below.
    if exam.has_papers:
        banner_text = f'{exam.get_exam_category_display().upper()} EXAMINATION SLIP'
    banner = Table(
        [[Paragraph(banner_text, styles['Banner'])]], colWidths=[doc.width]
    )
    banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), NAVY),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(banner)
    elements.append(Spacer(1, 6 * mm))

    rows = [
        ('Candidate Name', exam.candidate_name),
        ('Exam Number', exam.exam_number),
        ('Receipt Number', exam.receipt_number),
        ('Company', exam.company_display),
        ('Exam Category', exam.get_exam_category_display()),
        ('Paper', exam.paper_type_label or 'Not specified'),
    ]
    if not exam.has_papers:
        rows.extend([
            (
                'Exam Date',
                exam.exam_date.strftime('%A, %d %B %Y')
                if exam.exam_date
                else 'To be advised',
            ),
            (
                'Exam Time',
                exam.exam_time.strftime('%H:%M') if exam.exam_time else 'To be advised',
            ),
            ('Venue', _value(exam.venue)),
        ])

    data = [
        [
            Paragraph(f'<b>{label}</b>', styles['Normal']),
            Paragraph(str(value), styles['Normal']),
        ]
        for label, value in rows
    ]
    detail_table = Table(data, colWidths=[45 * mm, doc.width - 45 * mm])
    detail_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, RULE),
    ]))
    elements.append(detail_table)

    # Legacy multi-paper records carry their schedule per paper rather than on
    # the record itself.
    if exam.has_papers:
        elements.append(Spacer(1, 4 * mm))
        for paper in exam.papers.all():
            elements.append(_paper_block(paper, doc, styles))
            elements.append(Spacer(1, 3 * mm))

    elements.append(Spacer(1, 6 * mm))

    qr_bytes = base64.b64decode(generate_qr_base64(exam))
    qr_image = Image(io.BytesIO(qr_bytes), width=28 * mm, height=28 * mm)
    footer_left = Paragraph(
        f'<font size="8">Generated: {generated_at.strftime("%d %b %Y, %H:%M")} WAT<br/>'
        f'Officer: {officer_username}</font>',
        styles['Normal'],
    )
    footer = Table([[footer_left, qr_image]], colWidths=[doc.width - 32 * mm, 32 * mm])
    footer.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(footer)
    return elements


def _paper_block(paper, doc, styles):
    """A bordered block showing one paper's date, time and venue.

    Only reached for legacy records. A current record has one paper and one
    schedule, both shown in the detail table.
    """
    rows = [
        [Paragraph(paper.get_paper_display(), styles['PaperTitle']), ''],
        [
            Paragraph('<b>Date</b>', styles['Normal']),
            Paragraph(
                paper.exam_date.strftime('%A, %d %B %Y')
                if paper.exam_date
                else 'To be advised',
                styles['Normal'],
            ),
        ],
        [
            Paragraph('<b>Time</b>', styles['Normal']),
            Paragraph(
                paper.exam_time.strftime('%H:%M')
                if paper.exam_time
                else 'To be advised',
                styles['Normal'],
            ),
        ],
        [
            Paragraph('<b>Venue</b>', styles['Normal']),
            Paragraph(_value(paper.venue), styles['Normal']),
        ],
    ]
    table = Table(rows, colWidths=[30 * mm, doc.width - 30 * mm])
    table.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BOX', (0, 0), (-1, -1), 0.5, RULE),
        ('LINEBEFORE', (0, 0), (0, -1), 2, NAVY),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ]))
    return table


def render_slip_pdf_reportlab(exam: ExamSchedule, request=None) -> bytes:
    buffer = io.BytesIO()
    doc = _document(buffer)
    styles = _styles()
    doc.build(_slip_elements(exam, doc, styles, _slip_context(exam, request)))
    return buffer.getvalue()


def render_slips_pdf_reportlab(exams, request=None) -> bytes:
    """One PDF holding every slip, a page each."""
    exams = list(exams)
    if not exams:
        raise ValueError('No examination records to render.')

    buffer = io.BytesIO()
    doc = _document(buffer)
    styles = _styles()

    elements = []
    for index, exam in enumerate(exams):
        if index:
            elements.append(PageBreak())
        elements.extend(_slip_elements(exam, doc, styles, _slip_context(exam, request)))

    doc.build(elements)
    return buffer.getvalue()
