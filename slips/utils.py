import base64
import io
import json
import logging

import qrcode
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from exams.models import ExamSchedule

logger = logging.getLogger(__name__)


def build_qr_payload(exam: ExamSchedule) -> str:
    data = {
        'candidate_name': exam.candidate_name,
        'exam_number': exam.exam_number,
        'exam_date': exam.exam_date.isoformat() if exam.exam_date else None,
    }
    return json.dumps(data, separators=(',', ':'))


def generate_qr_base64(exam: ExamSchedule) -> str:
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(build_qr_payload(exam))
    qr.make(fit=True)
    img = qr.make_image(fill_color='#1A1B5D', back_color='white')
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


def get_slip_context(exam: ExamSchedule, request=None) -> dict:
    from django.contrib.staticfiles import finders

    generated_at = timezone.localtime(timezone.now())
    logo_path = finders.find('images/ncaa_logo.png')
    return {
        'exam': exam,
        'ncaa_full_name': settings.NCAA_FULL_NAME,
        'qr_base64': generate_qr_base64(exam),
        'generated_at': generated_at,
        'officer_username': exam.scheduled_by.username,
        'logo_path': f'file:///{logo_path}'.replace('\\', '/') if logo_path else '',
        'request': request,
    }


# ---------------------------------------------------------------------------
# Single slip
# ---------------------------------------------------------------------------
def render_slip_html(exam: ExamSchedule, request=None) -> str:
    context = get_slip_context(exam, request)
    return render_to_string('slips/exam_slip.html', context, request=request)


def render_slip_pdf_weasyprint(exam: ExamSchedule, request=None) -> bytes:
    from weasyprint import HTML

    html_string = render_slip_html(exam, request)
    base_url = request.build_absolute_uri('/') if request else None
    return HTML(string=html_string, base_url=base_url).write_pdf()


def render_slip_pdf(exam: ExamSchedule, request=None) -> bytes:
    """Generate a slip PDF.

    WeasyPrint produces the closer match to the HTML design and is what runs on
    the Linux server. It needs GTK, which Windows workstations do not have, so
    ReportLab renders the same slip when WeasyPrint cannot start.
    """
    try:
        return render_slip_pdf_weasyprint(exam, request)
    except Exception as exc:
        logger.info('WeasyPrint unavailable (%s); using the ReportLab renderer.', exc)
        from .pdf_reportlab import render_slip_pdf_reportlab

        return render_slip_pdf_reportlab(exam, request)


# ---------------------------------------------------------------------------
# Batch: every slip for one application
# ---------------------------------------------------------------------------
def render_slips_html(exams, request=None) -> str:
    slips = [get_slip_context(exam, request) for exam in exams]
    return render_to_string(
        'slips/slip_batch_pdf.html', {'slips': slips}, request=request
    )


def render_slips_pdf_weasyprint(exams, request=None) -> bytes:
    from weasyprint import HTML

    html_string = render_slips_html(exams, request)
    base_url = request.build_absolute_uri('/') if request else None
    return HTML(string=html_string, base_url=base_url).write_pdf()


def render_slips_pdf(exams, request=None) -> bytes:
    """One PDF containing every slip for an application, a page each."""
    exams = list(exams)
    if not exams:
        raise ValueError('No examination records to render.')

    try:
        return render_slips_pdf_weasyprint(exams, request)
    except Exception as exc:
        logger.info('WeasyPrint unavailable (%s); using the ReportLab renderer.', exc)
        from .pdf_reportlab import render_slips_pdf_reportlab

        return render_slips_pdf_reportlab(exams, request)
