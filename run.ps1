# run.ps1 — launch TrustLayer (FastAPI backend + Streamlit frontend).
# Usage:  ./run.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "Starting TrustLayer backend  -> http://127.0.0.1:8000" -ForegroundColor Cyan
Start-Process -FilePath "python" `
  -ArgumentList "-m","uvicorn","backend.main:app","--port","8000" `
  -WorkingDirectory $PSScriptRoot

Start-Sleep -Seconds 3
Write-Host "Starting TrustLayer frontend -> http://localhost:8501 (opens in browser)" -ForegroundColor Cyan
python -m streamlit run frontend/app.py
