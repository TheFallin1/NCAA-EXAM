"""Document validation: both documents mandatory, formats, size, integrity."""
from django.test import override_settings

from applications.models import Application, ProcessingStatus
from applications.services.documents import (
    DocumentValidationError,
    document_upload_path,
    validate_upload,
)

from .base import JPG_BYTES, PDF_BYTES, PNG_BYTES, WorkflowTestCase, upload


class UploadValidationTests(WorkflowTestCase):
    def test_accepts_pdf_jpg_png(self):
        cases = [
            ('scan.pdf', PDF_BYTES, 'pdf'),
            ('scan.png', PNG_BYTES, 'png'),
            ('scan.jpg', JPG_BYTES, 'jpg'),
            ('scan.jpeg', JPG_BYTES, 'jpeg'),
        ]
        for name, content, expected in cases:
            with self.subTest(name=name):
                extension, _ = validate_upload(upload(name, content))
                self.assertEqual(extension, expected)

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(DocumentValidationError) as ctx:
            validate_upload(upload('scan.docx', PDF_BYTES))
        self.assertIn('Unsupported file type', str(ctx.exception))

    def test_rejects_contents_that_contradict_the_extension(self):
        """A .pdf that is not a PDF is a failed scan, not a document."""
        with self.assertRaises(DocumentValidationError) as ctx:
            validate_upload(upload('scan.pdf', b'this is plain text'))
        self.assertIn('do not match', str(ctx.exception))

    def test_rejects_empty_file(self):
        with self.assertRaises(DocumentValidationError) as ctx:
            validate_upload(upload('scan.pdf', b''))
        self.assertIn('empty', str(ctx.exception))

    @override_settings(MAX_UPLOAD_SIZE=100)
    def test_rejects_oversized_file(self):
        with self.assertRaises(DocumentValidationError) as ctx:
            validate_upload(upload('scan.pdf', PDF_BYTES + b'0' * 500))
        self.assertIn('too large', str(ctx.exception))

    def test_stored_name_discards_user_supplied_path(self):
        """Path traversal is not expressible: only a UUID reaches the disk."""

        class Stub:
            application_id = 'abc'

        path = document_upload_path(Stub(), '../../../../etc/passwd.pdf')
        self.assertTrue(path.startswith('applications/abc/'))
        self.assertNotIn('..', path)
        self.assertNotIn('passwd', path)
        self.assertTrue(path.endswith('.pdf'))

    def test_unknown_extension_falls_back_to_bin(self):
        class Stub:
            application_id = 'abc'

        self.assertTrue(document_upload_path(Stub(), 'x.exe').endswith('.bin'))


class RequiredDocumentTests(WorkflowTestCase):
    """Scenarios B and C: either document missing blocks processing."""

    def test_both_documents_accepted(self):
        response = self.submit_application()
        self.assertEqual(response.status_code, 302)
        application = Application.objects.get()
        self.assertTrue(application.has_both_documents)
        self.assertEqual(application.processing_status, ProcessingStatus.REVIEW)

    def test_receipt_missing_is_rejected(self):
        response = self.submit_application(receipt=False)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'receipt', 'This field is required.'
        )
        self.assertFalse(Application.objects.exists())

    def test_application_letter_missing_is_rejected(self):
        response = self.submit_application(letter=False)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context['form'], 'application_letter', 'This field is required.'
        )
        self.assertFalse(Application.objects.exists())

    def test_no_examination_records_created_when_blocked(self):
        from exams.models import ExamSchedule

        self.submit_application(receipt=False)
        self.submit_application(letter=False)
        self.assertFalse(ExamSchedule.objects.exists())


class DocumentAccessTests(WorkflowTestCase):
    def test_documents_require_authentication(self):
        self.submit_application()
        document = Application.objects.get().letter

        self.client.logout()
        response = self.client.get(f'/applications/documents/{document.pk}/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_signed_in_officer_can_read_a_document(self):
        self.submit_application()
        document = Application.objects.get().letter

        response = self.client.get(f'/applications/documents/{document.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('inline', response['Content-Disposition'])

    def test_documents_have_no_public_url(self):
        self.submit_application()
        document = Application.objects.get().letter
        with self.assertRaises(ValueError):
            document.file.url

    def test_document_is_stored_outside_media_root(self):
        from django.conf import settings

        self.submit_application()
        document = Application.objects.get().letter
        self.assertNotIn(str(settings.MEDIA_ROOT), document.file.path)
        self.assertIn(str(settings.PRIVATE_MEDIA_ROOT), document.file.path)
