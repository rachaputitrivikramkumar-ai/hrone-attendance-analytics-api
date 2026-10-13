# Employee Attendance & Analytics API

A REST API built with **FastAPI** and **MongoDB** for employee management, attendance punch-in and punch-out, attendance corrections, and workforce analytics.

## Features

- Create and list employees with pagination and department filtering.
- Record attendance punch-in and punch-out.
- List attendance records with filters and pagination.
- Correct attendance records with an audit history.
- Generate monthly employee attendance analytics.
- Generate department summaries, late-arrival leaderboards, and department trends.
- Inspect MongoDB query execution plans to verify index usage.

## Technology Stack

- Python 3.11+
- FastAPI
- PyMongo
- MongoDB 6.0+
- Uvicorn

## Setup

1. Clone this repository and open the project directory.
2. Create and activate a virtual environment:

   **Windows PowerShell**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

4. Configure the environment variables `MONGO_URI` and `MONGO_DB` in a local `.env` file. Use your own MongoDB connection details and keep `.env` out of version control.

5. If sample data is needed, configure the database and run:

   ```powershell
   python sample_seed.py
   ```

## Run the API

From the repository root, run:

```powershell
python -m uvicorn app.main:app --port 8000 --reload
```

The API will be available at `http://127.0.0.1:8000`.

## API Documentation

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI schema: `http://127.0.0.1:8000/openapi.json`
- Health check: `GET /health`

## Main Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check API and database health |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| GET | `/attendance` | List attendance records |
| POST | `/attendance/punch-out` | Record punch-out |
| PATCH | `/attendance/{emp_code}/{date}` | Correct an attendance record |
| GET | `/analytics/employees/{emp_code}/monthly` | Monthly employee analytics |
| GET | `/analytics/departments/summary` | Department summary |
| GET | `/analytics/leaderboard/late` | Late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Department attendance trend |
| GET | `/admin/explain/{endpoint}` | Inspect query execution plans |

## Notes

- Employee records are identified by `emp_code`.
- Attendance dates use `YYYY-MM-DD`, and API timestamps use epoch milliseconds.
- Shift times and attendance dates follow Indian Standard Time (IST).
- Attendance and analytics calculations follow the assignment's specified business rules.
- MongoDB indexes are created by the application at startup.

See `REVIEW.md` for the starter-code review and `DECISIONS.md` for implementation decisions.