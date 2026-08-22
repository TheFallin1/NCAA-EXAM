# NCAA Aviation Examination Scheduling System

Web application for **Nigeria Civil Aviation Authority (NCAA)** examination officers.
Officers process a paper application digitally: the scanned application letter and
payment receipt are read by OCR, the extracted information is verified on screen,
examination IDs are issued, the examination is scheduled, and printable slips are
produced.

Designed for **on-premise deployment inside the NCAA network**. No part of the core
workflow depends on an external service, and no candidate document ever leaves the
NCAA server.

## Workflow

```
Officer login
      |
Process Application  ->  select examination type
      |
Provide application letter + payment receipt   (both mandatory)
      |
Validate documents  ->  OCR  ->  extract exam type, candidate names, receipt number
      |
Compare officer-selected type with the type detected in the letter
      |
   match? ----- no ----> STOP, mismatch shown, nothing is created
      |
     yes
      |
Officer verification  ->  correct any misreadings, confirm
      |
Generate examination IDs  ->  schedule  ->  generate slips  ->  print
```

Flight Dispatch additionally carries **Paper 1** and **Paper 2**, which can be
scheduled independently or share a single sitting.

## Features

- Secure officer login (no public registration)
- Application intake with mandatory letter + receipt
- Self-hosted OCR (Tesseract) with per-line confidence
- Candidate, examination-type and receipt-number extraction
- Mandatory examination-type match check that cannot be bypassed
- Officer verification screen with editable candidate names
- Server-generated, unique examination IDs
- Flight Dispatch Paper 1 / Paper 2 scheduling and slip layout
- Individual and batch examination slips (print or PDF)
- Dashboard with statistics, charts and calendar
- Search, filter, edit, delete and reprint records
- System admin portal for officer management and activity logs
- Full audit trail of every processing action
- PostgreSQL for production; SQLite for local development

## Tech stack

- Python / Django 5
- Django REST Framework (dashboard APIs)
- PostgreSQL / SQLite
- Tailwind CSS, Alpine.js, Chart.js — **vendored locally**, no CDN at runtime
- Tesseract OCR via pytesseract, pypdfium2 for PDF handling
- WeasyPrint (Linux) with a ReportLab fallback, qrcode

## Quick start (local)

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux
pip install -r requirements.txt
cp .env.example .env           # then edit it
python manage.py migrate
python manage.py create_officer admin --password YourSecurePassword --admin
python manage.py runserver
```

Open <http://127.0.0.1:8000/accounts/login/>.

To load demo officers and sample records: `python manage.py seed_demo_data`.

## Running a demonstration

Everything runs on one machine, which is also how NCAA will run it in
production. Install Tesseract (see below), then:

```powershell
.\run_demo.ps1
```

That applies migrations, creates the demo accounts, generates sample scanned
documents, confirms the OCR engine is working, and opens the browser. Or do it
by hand:

```bash
python manage.py prepare_demo
python manage.py runserver
```

| | |
|---|---|
| URL | <http://127.0.0.1:8000/accounts/login/> |
| Officer | `officer` / `Officer@2025` |
| Administrator | `admin` / `Admin@2025` (portal at `/system/`) |

`prepare_demo` writes sample documents to `demo_documents/`:

- **`scans/`** — page images with no text layer. These go through genuine
  Tesseract recognition, so they are what to use in front of an audience.
- **`digital/`** — the same letters as PDFs carrying a text layer, read
  directly and near-instantly.

`demo_documents/README.txt` says which examination type to select for each one.
The set covers a straightforward five-candidate Pilot application, a Flight
Dispatch application (Paper 1 / Paper 2), a bulleted list, a tabulated list, and
a deliberate examination-type mismatch to show processing being blocked.

Reading a scanned letter and receipt takes roughly 3-5 seconds on a laptop.

## Hosting

**Tesseract is not in this repository and cannot be.** It is a native binary
(~240 MB installed), not a Python package, and the build for one operating
system will not run on another. It has to be installed on whichever machine
serves the application.

That rules out some hosts:

| Host | Works? | Why |
|---|---|---|
| On-premise server | Yes | The target deployment. `apt-get install tesseract-ocr`. |
| Local machine | Yes | What the demo instructions above use. |
| Render (Docker) | Yes | Use the included `Dockerfile`; `render.yaml` is configured for it. |
| Render (native Python) | **No** | Builds run without root, so Tesseract cannot be installed. |
| Vercel | **No** | Serverless: no way to install Tesseract, a read-only filesystem with nowhere to keep documents, background threads are killed once the response is sent, and the execution timeout is shorter than a multi-page recognition run. |

## OCR setup

The application talks to OCR through a service layer, so the engine is
configuration, not code. **Tesseract** is the supported engine: it installs from
the OS package manager, downloads no models at first run (which matters on an
isolated network), needs no GPU, and reports the per-word confidence the
verification screen relies on.

### Install Tesseract

```bash
# Debian / Ubuntu
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng

# RHEL / Rocky
sudo dnf install -y tesseract tesseract-langpack-eng
```

Windows: install the UB Mannheim build, then set
`OCR_ENGINE_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe`.

Verify with `tesseract --version`. If the binary is not on `PATH`, set
`OCR_ENGINE_PATH` in `.env`.

### What is extracted from each document

The two documents have separate extractors and separate responsibilities.

```
APPLICATION LETTER                 PAYMENT RECEIPT
        |                                 |
       OCR                               OCR
        |                                 |
ApplicationExtractor              ReceiptExtractor
        |                                 |
  Company                          Official Receipt Number
  Candidate name(s)
  Examination type
```

**Examination type** is decided from context, not from keywords. A letter
headed *"REQUEST FOR EXAM DATE FOR CABIN CREW AB-INITIO STUDENTS"* is a Cabin
Crew application even though its body mentions a *Boeing 737 Classic Type
rating exam* -- a type named inside an examination context outranks aviation
vocabulary mentioned in passing. The result is always one of the four
configured types; nothing new is ever invented.

**Candidate names** come from the list the letter submits, not from every name
on the page. The recipient, the signatory and the accountable manager are
excluded by the surrounding structure and vocabulary.

**Company** is the applicant, taken from the letterhead or the `For:` line of
the signature block -- never the NCAA addressee.

**The receipt** yields one field: the Official Receipt Number. An NCAA receipt
also carries an invoice number, a date, a period and an amount, so the number
is found by locating the *Official Receipt ... No* label and reading the field
beside it, rather than by taking the first number on the page. Where the
whole-page pass is too coarse for small print, that one field is read again
enlarged and at high contrast.

Everything above is shown to the officer for correction before any examination
record exists.

### How documents are read

1. **PDF with an embedded text layer** — read directly. Exact, and much faster
   than recognition. Most scanners can produce searchable PDFs; enabling that
   on the office scanner measurably improves accuracy.
2. **Scanned PDF** — rasterised at `OCR_DPI` (300 by default) and recognised.
3. **JPG / PNG** — recognised directly.

Any scanner that outputs PDF, JPG or PNG works. No particular model or brand
is required, and a photograph taken on a phone is acceptable.

Before recognition each page is **cropped to the sheet** (the desk around a
photographed document otherwise derails page segmentation badly enough that
small print stops being read), **turned the right way up**, **enlarged** if it
was photographed at low resolution, and **straightened**. Orientation is
decided by reading a small probe of the page at all four rotations and keeping
whichever reads best; Tesseract's own orientation detection is not used,
because on these scans it reports near-zero confidence and the wrong script.

### Tuning

| Setting | Purpose |
|---|---|
| `OCR_CONFIDENCE_THRESHOLD` | Below this percentage a reading is flagged for officer review |
| `OCR_DPI` | Raise to 400 for faint or small print; costs processing time |
| `OCR_MAX_PAGES` | Page cap per document |
| `OCR_BACKGROUND` | Run OCR in a worker thread (default) or inline |

## On-premise deployment

```
              NCAA Local Network
                      |
             NCAA Physical Server
                      |
        +-------------+-------------+
        |             |             |
     Django       PostgreSQL   Tesseract OCR
   (gunicorn)                  (local binary)
        |
      nginx
```

Nothing above needs internet access. Front-end libraries are served from
`static/vendor/`, so the interface works on an isolated network.

### 1. System packages

```bash
sudo apt-get install -y python3-venv postgresql nginx \
    tesseract-ocr tesseract-ocr-eng \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2   # WeasyPrint
```

### 2. Database

```bash
sudo -u postgres createuser ncaa --pwprompt
sudo -u postgres createdb ncaa_exams --owner ncaa
```

Set `DATABASE_URL=postgresql://ncaa:password@localhost:5432/ncaa_exams`.

### 3. Document store

```bash
sudo mkdir -p /var/lib/ncaa-exams/private_media
sudo chown ncaa:ncaa /var/lib/ncaa-exams/private_media
sudo chmod 700 /var/lib/ncaa-exams/private_media
```

Set `PRIVATE_MEDIA_ROOT=/var/lib/ncaa-exams/private_media`.

This directory holds scanned letters and receipts. Keep it **outside** any
web-served path — it must never be reachable except through the authenticated
document view. Include it in the server's backup schedule.

### 4. Application

```bash
./build.sh                       # installs, collects static, migrates, seeds admin
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
```

Run gunicorn under systemd and put nginx in front of it for TLS.

### 5. Recovery job (recommended)

OCR runs in a background thread. If the server restarts mid-run, that work is
lost; this command finishes queued applications and clears any that stalled.

```cron
*/10 * * * * cd /opt/ncaa-exams && venv/bin/python manage.py process_ocr_queue
```

### 6. Optional: accelerated document serving

To let nginx stream documents instead of Django:

```nginx
location /protected/ {
    internal;
    alias /var/lib/ncaa-exams/private_media/;
}
```

Then set `PRIVATE_MEDIA_ACCEL_HEADER=X-Accel-Redirect` and
`PRIVATE_MEDIA_ACCEL_PREFIX=/protected/`.

## Security notes

- Scanned documents live outside `MEDIA_ROOT` and have **no public URL** —
  requesting one raises an error by design. They are served only by
  `applications:document`, which requires an authenticated officer.
- Stored filenames are UUIDs with a whitelisted extension. No user-supplied text
  reaches the filesystem, so path traversal is not expressible.
- Uploads are checked by extension **and** magic bytes, and capped by
  `MAX_UPLOAD_SIZE`.
- Every processing action is written to the activity log with the officer, time,
  IP address, and before/after values for corrections.

## Running the tests

```bash
python manage.py test
```

The suite uses a fake OCR engine, so **Tesseract is not required to run it** and
extraction assertions are deterministic.

## Management commands

```bash
# Create an officer
python manage.py create_officer username --password secret [--admin] \
    [--email] [--first-name] [--last-name] [--employee-id] [--phone]

# Seed the first administrator from environment variables
python manage.py seed_deployment_admin

# Process queued applications and recover stalled ones
python manage.py process_ocr_queue [--reclaim-only] [--timeout SECONDS]

# Development sample data
python manage.py seed_demo_data
```

## Project structure

```
config/         Settings, URLs
accounts/       Authentication, OfficerProfile, access mixins
applications/   Application intake, OCR, extraction, verification
  services/     ocr.py, extraction.py, processing.py, confirmation.py, jobs.py
exams/          ExamSchedule, ExamPaper, examination-type vocabulary, ID generation
dashboard/      Dashboard, admin portal, audit trail
slips/          Slip preview, PDF and batch printing
templates/      HTML templates
static/         CSS, JS, vendored front-end libraries, images
```

## Data model

```
Application                     one paper submission
├── ApplicationDocument         letter + receipt (one each, enforced)
├── ExtractedCandidate          staging; officer-editable, pre-confirmation
└── ExamSchedule (many)         one per candidate, created only on confirmation
    └── ExamPaper (0 or 2)      Flight Dispatch Paper 1 and Paper 2
```

Examination records created under the older manual workflow have no application
and are unaffected.

## License

Internal use — Nigeria Civil Aviation Authority.
