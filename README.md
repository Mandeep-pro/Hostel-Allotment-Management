# Manasbal Hostel Allotment

A Flask website for collecting student names and unique enrollment numbers, then randomly allotting registered students into Manasbal hostel rooms of exactly six students.

## Run locally

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install packages and start the site:

   ```powershell
   pip install -r requirements.txt
   python app.py
   ```

3. Open `http://127.0.0.1:5000` for the student welcome page. Students can check their assigned room and roommates at `/my-allotment`.

The administrator dashboard is at `/admin` and requires a login. For local testing, the default credentials are `admin` / `manasbal123`. Before deployment, set the `HOSTEL_ADMIN_USERNAME` and `HOSTEL_ADMIN_PASSWORD` environment variables to strong private values.

The SQLite database is created automatically as `hostel_allotment.db`. Change the Flask secret key and protect `/admin` with authentication before deploying publicly.
