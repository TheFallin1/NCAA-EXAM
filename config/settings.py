"""
Django settings for NCAA Aviation Examination Scheduling System.
"""
import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ['localhost', '127.0.0.1']),
)

env_file = BASE_DIR / '.env'
if env_file.exists():
    environ.Env.read_env(env_file, overwrite=True)

SECRET_KEY = env('SECRET_KEY', default='django-insecure-dev-only-change-in-production')
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])
render_external_hostname = env('RENDER_EXTERNAL_HOSTNAME', default='')
if render_external_hostname and render_external_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_external_hostname)

vercel_url = env('VERCEL_URL', default='')
vercel_project_url = env('VERCEL_PROJECT_PRODUCTION_URL', default='')
if vercel_url:
    if vercel_url not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(vercel_url)
    # Vercel deployments can be accessed via multiple subdomains
    if '.vercel.app' not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append('.vercel.app')
if vercel_project_url and vercel_project_url not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(vercel_project_url)

CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
if render_external_hostname:
    render_origin = f'https://{render_external_hostname}'
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)
if vercel_url:
    vercel_origin = f'https://{vercel_url}'
    if vercel_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(vercel_origin)
    # Trust all Vercel subdomains for CSRF
    vercel_wildcard = 'https://*.vercel.app'
    if vercel_wildcard not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(vercel_wildcard)
if vercel_project_url:
    project_origin = f'https://{vercel_project_url}'
    if project_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(project_origin)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'rest_framework',
    'accounts',
    'exams',
    'dashboard',
    'slips',
    'applications',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'config.context_processors.site_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

database_url = env('DATABASE_URL', default='')
if database_url:
    DATABASES = {'default': env.db('DATABASE_URL')}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'whitenoise.storage.CompressedStaticFilesStorage'
        ),
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'dashboard:home'
LOGOUT_REDIRECT_URL = 'accounts:login'

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
}

# NCAA branding
NCAA_FULL_NAME = 'Nigeria Civil Aviation Authority'
NCAA_LOGO_URL = 'images/ncaa_logo.png'

# Security (production via env)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    # Off by default: enabling HSTS on an internal network before TLS is
    # settled locks browsers out. Set once the NCAA server has a trusted
    # certificate, e.g. 31536000 for one year.
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
        'SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False
    )

GROUP_EXAMINATION_OFFICER = 'Examination Officer'
GROUP_SYSTEM_ADMIN = 'System Admin'


# ---------------------------------------------------------------------------
# Document intake / private storage (on-premise: never leaves NCAA control)
# ---------------------------------------------------------------------------
PRIVATE_MEDIA_ROOT = Path(
    env('PRIVATE_MEDIA_ROOT', default=str(BASE_DIR / 'private_media'))
)
MAX_UPLOAD_SIZE = env.int('MAX_UPLOAD_SIZE', default=10 * 1024 * 1024)
ALLOWED_UPLOAD_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']

# Django's own upload guards, kept just above our application-level limit so a
# hostile request is rejected by the framework before it reaches a view.
FILE_UPLOAD_MAX_MEMORY_SIZE = min(MAX_UPLOAD_SIZE, 2 * 1024 * 1024)
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_SIZE + (1024 * 1024)

# Optional nginx/apache accelerated file serving for the authenticated
# document view. Leave empty to stream through Django.
PRIVATE_MEDIA_ACCEL_HEADER = env('PRIVATE_MEDIA_ACCEL_HEADER', default='')
PRIVATE_MEDIA_ACCEL_PREFIX = env('PRIVATE_MEDIA_ACCEL_PREFIX', default='/protected/')

# ---------------------------------------------------------------------------
# OCR (self-hosted; no external cloud services)
# ---------------------------------------------------------------------------
OCR_ENGINE = env('OCR_ENGINE', default='tesseract')  # 'tesseract' | 'fake'
OCR_ENGINE_PATH = env('OCR_ENGINE_PATH', default='')  # tesseract binary path
OCR_LANGUAGES = env('OCR_LANGUAGES', default='eng')
OCR_DPI = env.int('OCR_DPI', default=300)
OCR_MAX_PAGES = env.int('OCR_MAX_PAGES', default=20)
OCR_CONFIDENCE_THRESHOLD = env.float('OCR_CONFIDENCE_THRESHOLD', default=80.0)
OCR_TIMEOUT_SECONDS = env.int('OCR_TIMEOUT_SECONDS', default=300)
# Run OCR in a worker thread so the officer's request returns immediately.
# Turn off to process inline (the test suite does this for determinism).
OCR_BACKGROUND = env.bool('OCR_BACKGROUND', default=True)

# --- Page preparation ------------------------------------------------------
# Scans arrive sideways and upside down. The correct rotation is found by
# recognising a small probe of the page at each of the four orientations and
# keeping whichever reads best.
OCR_AUTO_ROTATE = env.bool('OCR_AUTO_ROTATE', default=True)
OCR_DESKEW = env.bool('OCR_DESKEW', default=True)
# Long edge of the cheap probe used to compare orientations.
OCR_ORIENTATION_PROBE_EDGE = env.int('OCR_ORIENTATION_PROBE_EDGE', default=700)
# Turning the page must be a clear improvement, not a coin flip: two
# orientations can both yield plausible-looking text.
OCR_ROTATION_MARGIN = env.float('OCR_ROTATION_MARGIN', default=1.15)
# A photographed A4 page is often far below the ~300 DPI Tesseract expects.
OCR_MIN_LONG_EDGE = env.int('OCR_MIN_LONG_EDGE', default=2200)
OCR_MAX_UPSCALE = env.float('OCR_MAX_UPSCALE', default=4.0)
# Residual tilt correction, in degrees.
# Officers photograph documents on a desk; the dark surround has to go before
# small print such as a receipt number can be read.
OCR_CROP_TO_PAGE = env.bool('OCR_CROP_TO_PAGE', default=True)
# Enlargement used when re-reading a single field, such as the receipt number.
OCR_FIELD_SCALE = env.int('OCR_FIELD_SCALE', default=6)
OCR_REGION_WORK_EDGE = env.int('OCR_REGION_WORK_EDGE', default=700)
OCR_REGION_MIN_COVERAGE = env.float('OCR_REGION_MIN_COVERAGE', default=0.25)
OCR_MIN_SKEW = env.float('OCR_MIN_SKEW', default=0.4)
OCR_MAX_SKEW = env.float('OCR_MAX_SKEW', default=15.0)
# A PDF carrying at least this many characters of real text is trusted as a
# digital original and read directly instead of being rasterised and OCR'd.
# Kept low because a payment receipt is legitimately short: the distinction
# being drawn is "has a text layer" versus "is a picture of a page", and an
# unsearchable scan carries essentially none. If a partial layer ever slips
# through, no candidates are found and the officer is asked to rescan, so the
# failure is visible rather than silent.
OCR_PDF_TEXT_LAYER_MIN_CHARS = env.int('OCR_PDF_TEXT_LAYER_MIN_CHARS', default=50)

# ---------------------------------------------------------------------------
# Examination structure
# ---------------------------------------------------------------------------
EXAM_NUMBER_PREFIX = env('EXAM_NUMBER_PREFIX', default='NCAA')
# NCAA runs Flight Dispatch Paper 1 and Paper 2 on different days, so the
# "both papers share one schedule" option starts switched off. Officers can
# still tick it per application if a sitting is ever combined.
FLIGHT_DISPATCH_SHARED_SCHEDULE_DEFAULT = env.bool(
    'FLIGHT_DISPATCH_SHARED_SCHEDULE_DEFAULT', default=False
)
