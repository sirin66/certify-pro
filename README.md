# CertifyPro - Student Certificate Generator

Automated student certificate generation from CSV / Google Sheet data directly uploaded to Google Drive.

## Quick Start

1. Set up a Python virtual environment:
   ```powershell
   cd backend
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Add your Google Cloud Service Account JSON key:
   - Save your key file as `backend/service_account.json`

3. Run the backend:
   ```powershell
   python app.py
   ```

4. Open your browser:
   - Navigate to `http://127.0.0.1:5000`

