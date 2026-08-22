# NCAA Examination Scheduling - demonstration launcher.
# Right-click > Run with PowerShell, or:  .\run_demo.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'Virtual environment not found. Creating it...' -ForegroundColor Yellow
    python -m venv venv
    & $python -m pip install --upgrade pip --quiet
    & $python -m pip install -r requirements.txt
}

& $python manage.py prepare_demo
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ''
Write-Host 'Starting the server. Press Ctrl+C to stop.' -ForegroundColor Cyan
Write-Host ''
Start-Process 'http://127.0.0.1:8000/accounts/login/'
& $python manage.py runserver 8000
