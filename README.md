# NCAA Aviation Examination Scheduling System

Enterprise web application for the **Nigeria Civil Aviation Authority (NCAA)** examination officers to schedule aviation examinations and generate printable PDF examination slips.

## Features

- Secure officer login (no public registration)
- Fast exam scheduling with duplicate exam number prevention
- Professional examination slips with QR codes (WeasyPrint PDF)
- Dashboard with statistics, charts, and calendar
- Search, filter, edit, delete, and reprint records
- System admin portal for officer management and activity logs
- PostgreSQL (Supabase) for production; SQLite for local dev

## Tech stack

- Python / Django 5
- Django REST Framework (dashboard APIs)
- PostgreSQL (Supabase) / SQLite
- Tailwind CSS, Alpine.js
- WeasyPrint, qrcode

## Quick start (local)

### 1. Clone and enter project

```bash
cd ncaa_exam_system
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 2. Environment

Copy `.env.example` to `.env`:

```bash
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
# DATABASE_URL=   # leave empty for SQLite
```

### 3. Logo

Download the NCAA logo:

```bash
mkdir -p static/images
curl -o static/images/ncaa_logo.png https://www.ncaa.gov.ng/images/logo.png
```

On Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path static\images
Invoke-WebRequest -Uri "https://www.ncaa.gov.ng/images/logo.png" -OutFile "static\images\ncaa_logo.png"
```

### 4. Database and superuser

```bash
python manage.py migrate
python manage.py create_officer admin --password YourSecurePassword --admin
```

Or create Django superuser: `python manage.py createsuperuser`

### 5. Run server

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000/accounts/login/

## Supabase PostgreSQL

1. Create a project at [https://supabase.com](https://supabase.com)
2. Open **Project Settings > Database > Connection string**
3. Copy the **Transaction pooler** URI and replace `[YOUR-PASSWORD]` with your database password
4. Set in `.env`:

```
DATABASE_URL=postgresql://postgres.project-ref:password@aws-0-region.pooler.supabase.com:6543/postgres?sslmode=require
```

5. Run migrations: `python manage.py migrate`

Use Supabase's **transaction pooler** URL on Render for better connection handling.

## WeasyPrint on Windows

PDF generation requires GTK on Windows. Options:

- Deploy on Linux (Render) where WeasyPrint works out of the box
- Use WSL for local PDF testing
- HTML print view always works via browser **Print**

## Deployment (Render)

1. Push to GitHub
2. Create a **Web Service** on Render, connect the repo
3. Set root directory to `ncaa_exam_system` if the repo root is `NCAA/`
4. Build command: `./build.sh` (or `bash build.sh`)
5. Start command: `gunicorn config.wsgi:application`
6. Environment variables:
   - `SECRET_KEY`
   - `DEBUG=False`
   - `DATABASE_URL` (Supabase)
   - `ALLOWED_HOSTS=your-app.onrender.com`

## Management commands

```bash
python manage.py create_officer username --password secret [--admin] [--email] [--first-name] [--last-name]
```

## Project structure

```
config/       Settings, URLs
accounts/     Authentication, OfficerProfile
exams/        ExamSchedule CRUD
dashboard/    Dashboard, admin portal, activity logs
slips/        PDF and slip views
templates/    HTML templates
static/       CSS, JS, images
```

## License

Internal use — Nigeria Civil Aviation Authority.
