"""Upload validation and private document storage.

Documents scanned from paper applications contain personal data, so they are
kept outside MEDIA_ROOT, are never routed through the static/media servers, and
are only reachable through an authenticated view.
"""
import hashlib
import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible
from django.utils.functional import cached_property


class DocumentValidationError(Exception):
    """Raised when an uploaded file is not an acceptable scan."""


# Extension -> (canonical content type, accepted magic-byte prefixes).
# The extension alone is not trusted; the file header must agree with it.
_SIGNATURES = {
    'pdf': ('application/pdf', (b'%PDF-',)),
    'png': ('image/png', (b'\x89PNG\r\n\x1a\n',)),
    'jpg': ('image/jpeg', (b'\xff\xd8\xff',)),
    'jpeg': ('image/jpeg', (b'\xff\xd8\xff',)),
}

_MAX_SIGNATURE_LEN = max(
    len(prefix) for _, prefixes in _SIGNATURES.values() for prefix in prefixes
)


@deconstructible(path='applications.services.documents.PrivateDocumentStorage')
class PrivateDocumentStorage(FileSystemStorage):
    """Storage for scanned documents, rooted at PRIVATE_MEDIA_ROOT.

    The location is resolved on first access rather than at import, so the
    deployed path comes from configuration instead of being frozen into the
    field when Django starts. Nothing here is reachable over HTTP: the only
    route to these files is the authenticated document view.
    """

    @cached_property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PRIVATE_MEDIA_ROOT)

    @cached_property
    def location(self):
        return os.path.abspath(self.base_location)

    def _clear_cached_properties(self, setting, **kwargs):
        super()._clear_cached_properties(setting, **kwargs)
        if setting == 'PRIVATE_MEDIA_ROOT':
            self.__dict__.pop('base_location', None)
            self.__dict__.pop('location', None)

    def url(self, name):
        raise ValueError(
            'Scanned application documents have no public URL. Serve them '
            'through applications:document, which checks authentication.'
        )


private_storage = PrivateDocumentStorage()


def document_upload_path(instance, filename):
    """Build the stored path.

    The name the officer's scanner produced is recorded separately on the
    model but never used on disk: the stored name is a fresh UUID plus a
    whitelisted extension, so no user-supplied text reaches the filesystem and
    path traversal is not expressible.
    """
    extension = extension_for(filename)
    return 'applications/{application_id}/{name}.{ext}'.format(
        application_id=instance.application_id,
        name=uuid.uuid4().hex,
        ext=extension,
    )


def extension_for(filename):
    """Whitelisted lower-case extension for a filename, or 'bin' if unknown."""
    extension = os.path.splitext(filename or '')[1].lower().lstrip('.')
    return extension if extension in _SIGNATURES else 'bin'


def validate_upload(uploaded_file):
    """Check an uploaded scan and return (extension, content_type).

    Raises DocumentValidationError with an officer-readable message.
    """
    if uploaded_file is None:
        raise DocumentValidationError('No file was provided.')

    name = getattr(uploaded_file, 'name', '') or ''
    extension = os.path.splitext(name)[1].lower().lstrip('.')
    if extension not in _SIGNATURES:
        raise DocumentValidationError(
            'Unsupported file type "{ext}". Provide the scan as PDF, JPG or PNG.'.format(
                ext=extension or os.path.basename(name) or 'unknown'
            )
        )

    size = getattr(uploaded_file, 'size', None)
    if size is None:
        raise DocumentValidationError('The uploaded file could not be read.')
    if size == 0:
        raise DocumentValidationError('The uploaded file is empty.')

    max_size = settings.MAX_UPLOAD_SIZE
    if size > max_size:
        raise DocumentValidationError(
            'File is too large ({actual:.1f} MB). The maximum is {limit:.0f} MB.'.format(
                actual=size / (1024 * 1024), limit=max_size / (1024 * 1024)
            )
        )

    content_type, prefixes = _SIGNATURES[extension]
    header = _read_header(uploaded_file)
    if not any(header.startswith(prefix) for prefix in prefixes):
        raise DocumentValidationError(
            'The file contents do not match a {ext} document. '
            'It may be corrupted — please rescan it.'.format(ext=extension.upper())
        )

    return extension, content_type


def _read_header(uploaded_file):
    """Read the leading magic bytes without disturbing the file position."""
    position = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else 0
    uploaded_file.seek(0)
    header = uploaded_file.read(_MAX_SIGNATURE_LEN)
    uploaded_file.seek(position)
    return header


def sha256_of(uploaded_file):
    """Content hash, used to spot a document uploaded twice."""
    position = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else 0
    uploaded_file.seek(0)
    digest = hashlib.sha256()
    for chunk in iter(lambda: uploaded_file.read(65536), b''):
        digest.update(chunk)
    uploaded_file.seek(position)
    return digest.hexdigest()
