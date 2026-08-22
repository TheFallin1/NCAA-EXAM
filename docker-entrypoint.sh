#!/usr/bin/env bash
# Container start-up: bring the database up to date, then serve.
set -o errexit
set -o nounset

python manage.py migrate --noinput

# Optional first administrator. The command requires both variables, so only
# run it when they are actually set.
if [ -n "${DEPLOYMENT_ADMIN_USERNAME:-}" ] && [ -n "${DEPLOYMENT_ADMIN_PASSWORD:-}" ]; then
    python manage.py seed_deployment_admin
fi

# Recover any application left mid-processing by a previous restart, so nothing
# is stuck showing "OCR in progress".
python manage.py process_ocr_queue --reclaim-only || true

exec gunicorn config.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --timeout "${GUNICORN_TIMEOUT:-120}"
