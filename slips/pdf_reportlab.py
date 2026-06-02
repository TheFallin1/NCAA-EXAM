"""ReportLab PDF slip generator (works on Windows without GTK)."""
import base64
import io

from django.conf import settings
from django.contrib.staticfiles import finders
from reportlab.lib import colors
from reportlab.lib.pagesizes import A5
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from exams.models import ExamSchedule

from .utils import generate_qr_base64


def render_slip_pdf_reportlab(exam: ExamSchedule, request=None) -> bytes:
    context_extras = {}
    if request:
        from .utils import get_slip_context

        context_extras = get_slip_context(exam, request)

    generated_at = context_extras.get('generated_at')
    officer_username = context_extras.get('officer_username', exam.scheduled_by.username)
    if generated_at is None:
        from django.utils import timezone

        generated_at = timezone.localtime(timezone.now())

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A5,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    navy = colors.HexColor('#1A1B5D')
    title_style = ParagraphStyle(
        'NCAATitle',
        parent=styles['Heading2'],
        textColor=navy,
        fontSize=11,
        alignment=1,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        'NCAASub',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1,
        spaceAfter=8,
    )
    banner_style = ParagraphStyle(
        'Banner',
        parent=styles['Heading3'],
        textColor=colors.white,
        fontSize=10,
        alignment=1,
    )

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

    elements.append(Paragraph(settings.NCAA_FULL_NAME.upper(), title_style))
    elements.append(Paragraph('Aviation Examination Scheduling System', subtitle_style))

    banner_table = Table(
        [[Paragraph('EXAMINATION SLIP', banner_style)]],
        colWidths=[doc.width],
    )
    banner_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), navy),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(banner_table)
    elements.append(Spacer(1, 6 * mm))

    rows = [
        ('Candidate Name', exam.candidate_name),
        ('Exam Number', exam.exam_number),
        ('Receipt Number', exam.receipt_number),
        ('Company', exam.company_name),
        ('Exam Type', exam.get_exam_type_display()),
        ('Exam Date', exam.exam_date.strftime('%A, %d %B %Y')),
        ('Exam Time', exam.exam_time.strftime('%H:%M')),
        ('Venue', exam.venue),
    ]
    data = [[Paragraph(f'<b>{label}</b>', styles['Normal']), Paragraph(str(value), styles['Normal'])] for label, value in rows]
    detail_table = Table(data, colWidths=[45 * mm, doc.width - 45 * mm])
    detail_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#DDE1E4')),
    ]))
    elements.append(detail_table)
    elements.append(Spacer(1, 8 * mm))

    qr_bytes = base64.b64decode(generate_qr_base64(exam))
    qr_image = Image(io.BytesIO(qr_bytes), width=28 * mm, height=28 * mm)

    footer_left = Paragraph(
        f'<font size="8">Generated: {generated_at.strftime("%d %b %Y, %H:%M")} WAT<br/>'
        f'Officer: {officer_username}</font>',
        styles['Normal'],
    )
    footer_table = Table(
        [[footer_left, qr_image]],
        colWidths=[doc.width - 32 * mm, 32 * mm],
    )
    footer_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
    ]))
    elements.append(footer_table)

    doc.build(elements)
    return buffer.getvalue()
