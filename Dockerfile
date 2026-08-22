# NCAA Aviation Examination Scheduling System
#
# Tesseract is a native binary, not a Python package, so it cannot live in the
# repository or in requirements.txt. It has to be installed on the host that
# serves the application -- which is what this image does.
#
# Render's native Python runtime builds without root and cannot apt-get, so a
# Docker service is the way to get OCR working on a hosted deployment.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tesseract-ocr / -eng : the OCR engine and English language data
# libpango* / libharfbuzz-subset0 / fonts-* : WeasyPrint's PDF rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        fonts-dejavu-core \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV OCR_ENGINE=tesseract \
    OCR_ENGINE_PATH=/usr/bin/tesseract \
    OCR_LANGUAGES=eng \
    PRIVATE_MEDIA_ROOT=/var/lib/ncaa-exams/private_media

RUN mkdir -p "$PRIVATE_MEDIA_ROOT" \
    && chmod 700 "$PRIVATE_MEDIA_ROOT"

# Static files are baked into the image so start-up stays fast. The key here is
# used only to let Django load during the build; the real one comes from the
# environment at run time.
RUN SECRET_KEY=build-time-only DEBUG=False \
    python manage.py collectstatic --noinput

# Fail the build rather than the demo if the OCR engine did not install.
RUN tesseract --version

RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
CMD ["./docker-entrypoint.sh"]
