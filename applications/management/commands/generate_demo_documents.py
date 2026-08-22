"""Produce realistic application letters and receipts for demonstrations.

Writes both a PDF (carrying a text layer, read directly and near-instant) and a
PNG (a flat page image with no text layer, which exercises genuine Tesseract
recognition). The PNGs are the honest demonstration: they are what a flatbed
scanner produces.

    python manage.py generate_demo_documents
"""
import io
from pathlib import Path

from django.core.management.base import BaseCommand

LETTERHEAD_RULE_Y = 40

# (slug, exam type to select, letterhead, address, body lines)
DOCUMENTS = [
    {
        'slug': '01_pilot',
        'select': 'Pilot',
        'company': 'SKYWAY AVIATION TRAINING ACADEMY LIMITED',
        'address': [
            '12 Airport Road, Ikeja, Lagos State',
            'Tel: +234 801 234 5678  |  training@skywayacademy.com.ng',
        ],
        'reference': 'SATA/NCAA/2026/031',
        'subject': 'APPLICATION FOR PILOT EXAMINATION',
        'intro': [
            'We hereby submit the following candidates for the examination:',
        ],
        'candidates': [
            'JOHN ADEWALE',
            'DAVID OKORO',
            'MICHAEL IBRAHIM',
            'PETER WILLIAMS',
            'SAMUEL ADEYEMI',
        ],
        'style': 'numbered',
        'signatory': 'Bola Ogunleye',
        'title': 'Training Manager',
        'receipt': 'NCAA/2026/004821',
        'amount': '250,000.00',
        'note': 'Five candidates, numbered list. The straightforward case.',
    },
    {
        'slug': '02_flight_dispatch',
        'select': 'Flight Dispatch',
        'company': 'MAX AIR DISPATCH SERVICES LIMITED',
        'address': [
            '4 Aminu Kano Crescent, Wuse II, Abuja',
            'Tel: +234 803 987 6543  |  ops@maxairdispatch.com.ng',
        ],
        'reference': 'MADS/NCAA/2026/007',
        'subject': 'APPLICATION FOR FLIGHT DISPATCH EXAMINATION',
        'intro': [
            'We write to present the under-listed candidates for the',
            'Flight Dispatch examination:',
        ],
        'candidates': [
            'TUNDE BAKARE',
            'HALIMA SADIQ',
            'CHINEDU EZEKWESILI',
        ],
        'style': 'numbered',
        'signatory': 'Aisha Mohammed',
        'title': 'Head of Operations',
        'receipt': 'NCAA/2026/004822',
        'amount': '180,000.00',
        'note': 'Flight Dispatch: shows the Paper 1 / Paper 2 scheduling and slip.',
    },
    {
        'slug': '03_cabin_crew',
        'select': 'Cabin Crew',
        'company': 'OVERLAND AIRWAYS LIMITED',
        'address': [
            'Hangar 3, Murtala Muhammed Airport, Lagos',
            'Tel: +234 802 111 2233  |  crew@overlandairways.com',
        ],
        'reference': 'OAL/HR/2026/114',
        'subject': 'APPLICATION FOR CABIN CREW EXAMINATION',
        'intro': [
            'Please find the list of candidates below:',
        ],
        'candidates': [
            'AMINA BELLO',
            'GRACE NWOSU',
            'BLESSING EZE',
            'KELECHI OBI',
        ],
        'style': 'bulleted',
        'signatory': 'Funmilayo Adeoye',
        'title': 'Crew Training Coordinator',
        'receipt': 'NCAA/2026/004823',
        'amount': '200,000.00',
        'note': 'Bulleted list instead of numbered: shows format tolerance.',
    },
    {
        'slug': '04_ame',
        'select': 'AME',
        'company': 'DANA AIRCRAFT MAINTENANCE SERVICES LIMITED',
        'address': [
            'Plot 9, Maintenance Base, Kano',
            'Tel: +234 805 444 7788  |  ame@danamaintenance.com.ng',
        ],
        'reference': 'DAMS/NCAA/2026/052',
        'subject': 'APPLICATION FOR AME EXAMINATION',
        'intro': [
            'The following candidates are presented for the examination:',
        ],
        'candidates': [
            'IBRAHIM MUSA',
            'YUSUF ABDULLAHI',
        ],
        'style': 'table',
        'signatory': 'Emeka Nwachukwu',
        'title': 'Maintenance Manager',
        'receipt': 'NCAA/2026/004824',
        'amount': '150,000.00',
        'note': 'Tabulated candidate list: shows table parsing.',
    },
    {
        'slug': '05_mismatch',
        'select': 'Pilot  (deliberately wrong)',
        'company': 'AERO CONTRACTORS TRAINING CENTRE',
        'address': [
            '1 Aviation Close, Ikeja, Lagos',
            'Tel: +234 807 222 3344  |  training@aerocontractors.com',
        ],
        'reference': 'ACT/NCAA/2026/018',
        'subject': 'APPLICATION FOR CABIN CREW EXAMINATION',
        'intro': [
            'We hereby submit the following candidates for the examination:',
        ],
        'candidates': [
            'NGOZI ANYANWU',
            'OLUWASEUN ADEBAYO',
        ],
        'style': 'numbered',
        'signatory': 'Rita Okonjo',
        'title': 'Training Officer',
        'receipt': 'NCAA/2026/004825',
        'amount': '200,000.00',
        'note': 'Select "Pilot" for this one: the letter says Cabin Crew, so '
                'processing is blocked. Demonstrates the mandatory match rule.',
    },
]


def _letter_pdf(spec):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    width, height = A4
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    left = 60
    y = height - 60

    pdf.setFont('Helvetica-Bold', 14)
    pdf.drawString(left, y, spec['company'])
    y -= 18
    pdf.setFont('Helvetica', 9)
    for line in spec['address']:
        pdf.drawString(left, y, line)
        y -= 12
    y -= 6
    pdf.setLineWidth(1)
    pdf.line(left, y, width - left, y)
    y -= 28

    pdf.setFont('Helvetica', 10)
    pdf.drawString(left, y, f"Ref: {spec['reference']}")
    pdf.drawRightString(width - left, y, '14 February 2026')
    y -= 30

    pdf.drawString(left, y, 'The Director General')
    y -= 14
    pdf.drawString(left, y, 'Nigeria Civil Aviation Authority')
    y -= 14
    pdf.drawString(left, y, 'Aviation House, Abuja')
    y -= 28

    pdf.drawString(left, y, 'Dear Sir,')
    y -= 26

    pdf.setFont('Helvetica-Bold', 11)
    pdf.drawString(left, y, spec['subject'])
    y -= 24

    pdf.setFont('Helvetica', 10)
    for line in spec['intro']:
        pdf.drawString(left, y, line)
        y -= 16
    y -= 10

    style = spec['style']
    if style == 'table':
        pdf.setFont('Helvetica-Bold', 10)
        pdf.drawString(left + 10, y, 'S/N')
        pdf.drawString(left + 60, y, 'CANDIDATE NAME')
        y -= 6
        pdf.line(left, y, width - left, y)
        y -= 16
        pdf.setFont('Helvetica', 10)
        for index, name in enumerate(spec['candidates'], start=1):
            pdf.drawString(left + 14, y, str(index))
            pdf.drawString(left + 60, y, name)
            y -= 18
    elif style == 'bulleted':
        pdf.setFont('Helvetica', 10)
        for name in spec['candidates']:
            pdf.drawString(left + 14, y, '-')
            pdf.drawString(left + 34, y, name)
            y -= 18
    else:
        pdf.setFont('Helvetica', 10)
        for index, name in enumerate(spec['candidates'], start=1):
            pdf.drawString(left + 14, y, f'{index}.')
            pdf.drawString(left + 40, y, name)
            y -= 18

    y -= 16
    pdf.setFont('Helvetica', 10)
    pdf.drawString(left, y, 'Kindly schedule the above candidates accordingly.')
    y -= 34
    pdf.drawString(left, y, 'Yours faithfully,')
    y -= 40
    pdf.setFont('Helvetica-Bold', 10)
    pdf.drawString(left, y, spec['signatory'])
    y -= 14
    pdf.setFont('Helvetica', 9)
    pdf.drawString(left, y, spec['title'])
    pdf.drawString(left, y - 12, spec['company'].title())

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _receipt_pdf(spec):
    from reportlab.lib.pagesizes import A5
    from reportlab.pdfgen import canvas

    width, height = A5
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A5)
    left = 45
    y = height - 55

    pdf.setFont('Helvetica-Bold', 12)
    pdf.drawCentredString(width / 2, y, 'NIGERIA CIVIL AVIATION AUTHORITY')
    y -= 16
    pdf.setFont('Helvetica', 9)
    pdf.drawCentredString(width / 2, y, 'Aviation House, Abuja')
    y -= 22
    pdf.setFont('Helvetica-Bold', 11)
    pdf.drawCentredString(width / 2, y, 'OFFICIAL PAYMENT RECEIPT')
    y -= 12
    pdf.line(left, y, width - left, y)
    y -= 30

    rows = [
        ('Receipt No:', spec['receipt']),
        ('Payer:', spec['company'].title()),
        ('Description:', spec['subject'].replace('APPLICATION FOR ', '').title()),
        ('Amount Paid:', f"NGN {spec['amount']}"),
        ('Payment Date:', '12 February 2026'),
        ('Transaction Ref:', 'TRX' + spec['receipt'].split('/')[-1]),
        ('Payment Channel:', 'Remita'),
    ]
    for label, value in rows:
        pdf.setFont('Helvetica-Bold', 10)
        pdf.drawString(left, y, label)
        pdf.setFont('Helvetica', 10)
        pdf.drawString(left + 110, y, value)
        y -= 22

    y -= 10
    pdf.line(left, y, width - left, y)
    y -= 18
    pdf.setFont('Helvetica-Oblique', 8)
    pdf.drawString(left, y, 'This receipt must accompany the examination application letter.')

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _rasterise(pdf_bytes, dpi=300):
    """Flatten a PDF to a page image, as a scanner would."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        image = document[0].render(scale=dpi / 72.0).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()
    finally:
        document.close()


class Command(BaseCommand):
    help = 'Generate sample application letters and receipts for a demonstration.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output', default='demo_documents',
            help='Directory to write the files into (default: demo_documents).',
        )
        parser.add_argument(
            '--dpi', type=int, default=300,
            help='Resolution for the scanned PNG versions (default: 300).',
        )

    def handle(self, *args, **options):
        output = Path(options['output'])
        (output / 'scans').mkdir(parents=True, exist_ok=True)
        (output / 'digital').mkdir(parents=True, exist_ok=True)

        guide = [
            'NCAA Examination Scheduling - demonstration documents',
            '=' * 60,
            '',
            'scans/   PNG page images with no text layer. These go through real',
            '         Tesseract recognition - use these to demonstrate OCR.',
            'digital/ PDFs carrying a text layer. Read directly, near-instant.',
            '',
        ]

        for spec in DOCUMENTS:
            letter = _letter_pdf(spec)
            receipt = _receipt_pdf(spec)

            (output / 'digital' / f"{spec['slug']}_letter.pdf").write_bytes(letter)
            (output / 'digital' / f"{spec['slug']}_receipt.pdf").write_bytes(receipt)
            (output / 'scans' / f"{spec['slug']}_letter.png").write_bytes(
                _rasterise(letter, options['dpi'])
            )
            (output / 'scans' / f"{spec['slug']}_receipt.png").write_bytes(
                _rasterise(receipt, options['dpi'])
            )

            guide.extend([
                f"{spec['slug']}",
                f"  Select examination type : {spec['select']}",
                f"  Candidates in letter    : {len(spec['candidates'])}",
                f"  Receipt number          : {spec['receipt']}",
                f"  {spec['note']}",
                '',
            ])
            self.stdout.write(f"  generated {spec['slug']}")

        (output / 'README.txt').write_text('\n'.join(guide), encoding='utf-8')

        self.stdout.write(self.style.SUCCESS(
            f'\nWrote {len(DOCUMENTS) * 4} files to {output.resolve()}\n'
            f'See {output / "README.txt"} for what to select for each one.'
        ))
