"""Shared fixtures for the application-processing tests.

The whole suite runs against the `fake` OCR engine, so it needs no Tesseract
installation and every extraction assertion is deterministic.
"""
import shutil
import tempfile

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from accounts.models import OfficerProfile
from applications.services.ocr import FakeEngine

# Minimal payloads that satisfy the magic-byte check. The fake OCR engine
# never reads the bytes, so no real document is needed.
PDF_BYTES = b'%PDF-1.4\n%test scan\n'
PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPG_BYTES = b'\xff\xd8\xff\xe0' + b'\x00' * 64


def upload(name='letter.pdf', content=PDF_BYTES, content_type='application/pdf'):
    return SimpleUploadedFile(name, content, content_type=content_type)


def letter_upload(name='letter.pdf'):
    return upload(name, PDF_BYTES, 'application/pdf')


def receipt_upload(name='receipt.pdf'):
    return upload(name, PDF_BYTES, 'application/pdf')


def create_officer(username='officer', admin=False):
    user = User.objects.create_user(username=username, password='testpass123')
    group, _ = Group.objects.get_or_create(name=settings.GROUP_EXAMINATION_OFFICER)
    user.groups.add(group)
    if admin:
        admin_group, _ = Group.objects.get_or_create(name=settings.GROUP_SYSTEM_ADMIN)
        user.groups.add(admin_group)
    OfficerProfile.objects.create(user=user)
    return user


PILOT_LETTER = """SKYWAY AVIATION TRAINING ACADEMY LIMITED
12 Airport Road, Ikeja, Lagos

The Director General
Nigeria Civil Aviation Authority

Dear Sir,

APPLICATION FOR PILOT EXAMINATION

We hereby submit the following candidates for the examination:

1. JOHN ADEWALE
2. DAVID OKORO
3. MICHAEL IBRAHIM
4. PETER WILLIAMS
5. SAMUEL ADEYEMI

Thank you.

Yours faithfully,
Bola Ogunleye
Training Manager
"""

# An individual applying for themselves: no letterhead, no organisation
# anywhere on the page. The applicant is recorded as PRIVATE.
PRIVATE_APPLICANT_LETTER = """The Director General
Nigeria Civil Aviation Authority
Corporate Headquarters
Abuja.

Dear Sir,

APPLICATION FOR PILOT EXAMINATION

I hereby apply to sit the examination on the date below:

1. CHINEDU OKAFOR

Thank you.

Yours faithfully,
Chinedu Okafor
"""

CABIN_CREW_LETTER = """OVERLAND AIRWAYS LIMITED

APPLICATION FOR CABIN CREW EXAMINATION

Please find the list of candidates below:
1. AMINA BELLO
2. GRACE NWOSU

Yours faithfully,
"""

AME_LETTER = """DANA MAINTENANCE SERVICES LIMITED

APPLICATION FOR AME EXAMINATION

The following candidates are presented for the examination:
1. IBRAHIM MUSA
2. YUSUF ABDULLAHI

Yours faithfully,
"""

FLIGHT_DISPATCH_LETTER = """MAX AIR DISPATCH UNIT

APPLICATION FOR FLIGHT DISPATCH EXAMINATION

We hereby submit the following candidates for the examination:
1. TUNDE BAKARE
2. HALIMA SADIQ

Yours faithfully,
"""

# Mirrors the wording and layout of a real NCAA submission: the examination
# type is stated only as "REQUEST FOR EXAM DATE FOR ... AB-INITIO STUDENTS",
# and the body mentions an unrelated type rating exam that must not sway the
# classification. Names are fictional.
CABIN_CREW_ABINITIO_LETTER = """AEROPORT COLLEGE OF AVIATION
college of aviation & travel mgt.

9th JULY, 2025
The Director General Civil Aviation,
Nigerian Civil Aviation Authority
Corporate Headquarters,
Nnamdi Azikiwe International Airport
Abuja.
ATTN-DOLTS
Dear Sir,

REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS

We wish to notify the Authority for the just concluded Cabin crew ab-initio
training. The training ended on the 4th JUNE, 2025, and we'd like to schedule
the students for Air - Law and Boeing 737 Classic Type rating exam in Lagos.
Please find students' names below:

1. ADAEZE FRANCA OKONKWO
2. JOSEPH JUDE KELECHI

Relevant documents are also attached.
Thank you.
Yours faithfully,
For: AEROPORT COLLEGE OF AVIATION
Dr. Oludayo Taiwo Gideon
Accountable Managers
"""

# Mirrors a second real submission. Three of its four list markers came back
# from recognition as commas rather than full stops, the subject says
# "STUDENT" in the singular, and the body names an Embraer type rating exam
# that is not the examination being applied for. Names are fictional.
COMMA_DELIMITED_LETTER = """LAGOS AVIATION ACADEMY

7th July, 2025
The Director General Civil Aviation
Nigerian Civil Aviation Authority (NCAA)
Corporate Headquarters
Nnamdi Azikiwe International Airport
Abuja.
ATTN - DOLTS
Dear Sir,

REQUEST FOR EXAM DATE FOR CABIN CREW STUDENT EMBRAER 135/145

The above subject refers

We wish to notify the Authority of the just concluded Cabin crew conversion
training. The training ended on Thursday June 26th, 2025 and we would like to
schedule the students for Embraer 135/145 Type rating exam.

Please find students'
1, ALSAYED RANDA BASSAM
2, NDUKA ISIOMA HOPE
3. UWALAKA UCHECHI JUDITH
4, PHILLIPS MONIOLUWA RITA

Relevant documents are also attached.

Thank you,
Yours faithfully,
For: Lagos Aviation Academy
Bolaji Durojaiye
Head of Training
"""

RECEIPT_TEXT = """NIGERIA CIVIL AVIATION AUTHORITY
OFFICIAL PAYMENT RECEIPT

Receipt No: NCAA/2026/004821
Amount Paid: NGN 50,000.00
Date: 12 March 2026
"""


class WorkflowTestCase(TestCase):
    """Base case with a signed-in officer and an isolated document store."""

    letter_text = PILOT_LETTER
    receipt_text = RECEIPT_TEXT

    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp(prefix='ncaa-test-media-')
        cls._settings = override_settings(
            PRIVATE_MEDIA_ROOT=cls._media_root,
            OCR_ENGINE='fake',
            OCR_BACKGROUND=False,
            # DEBUG defaults to False, which switches on the HTTPS redirect and
            # would turn every test-client request into a 301.
            SECURE_SSL_REDIRECT=False,
            # Test accounts do not need production-strength hashing.
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
        )
        cls._settings.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._settings.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        super().setUp()
        FakeEngine.reset()
        self.set_ocr_text(self.letter_text, self.receipt_text)
        self.officer = create_officer()
        self.client.force_login(self.officer)

    def tearDown(self):
        FakeEngine.reset()
        super().tearDown()

    def set_ocr_text(self, letter=None, receipt=None):
        FakeEngine.responses = {
            'letter': letter if letter is not None else '',
            'receipt': receipt if receipt is not None else '',
        }

    def default_paper(self, exam_category):
        """The first paper configured for a category, as the dropdown offers."""
        from exams import paper_types

        choices = paper_types.choices_for(exam_category)
        return choices[0][0] if choices else ''

    def submit_application(self, exam_category='pilot', paper_type=None,
                           letter=True, receipt=True):
        """POST the intake form and return the response.

        `paper_type` defaults to the first paper configured for the category,
        which is what the dependent dropdown would offer.
        """
        if paper_type is None:
            paper_type = self.default_paper(exam_category)
        data = {'exam_category': exam_category, 'paper_type': paper_type}
        if letter:
            data['application_letter'] = letter_upload()
        if receipt:
            data['receipt'] = receipt_upload()
        return self.client.post('/applications/process/', data)
