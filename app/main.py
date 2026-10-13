"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]


# Create MongoDB indexes at application startup
db.employees.create_index(
    [("emp_code", 1)],
    unique=True,
    name="uq_employees_emp_code"
)

db.attendance_logs.create_index(
    [("emp_code", 1), ("date", 1)],
    unique=True,
    name="uq_attendance_emp_code_date"
)

db.attendance_logs.create_index(
    [("date", -1), ("emp_code", 1)],
    name="ix_attendance_date_emp_code"
)

db.attendance_logs.create_index(
    [("emp_code", 1), ("date", -1)],
    name="ix_attendance_emp_code_date_desc"
)

db.attendance_logs.create_index(
    [("date", 1), ("status", 1)],
    name="ix_attendance_date_status"
)


IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    if punch_in.tzinfo is None:
        punch_in = punch_in.replace(tzinfo=timezone.utc)

    punch_in_ist = punch_in.astimezone(IST)

    hour, minute = map(int, shift_start.split(":"))

    shift_start_ist = punch_in_ist.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    # More than 10 minutes late; count whole elapsed minutes.
    late_minutes = int(
        (punch_in_ist - shift_start_ist).total_seconds() // 60
    )

    return late_minutes if late_minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="MongoDB is unavailable"
        )


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    if db.employees.find_one({"emp_code": body.emp_code}):
        raise HTTPException(409, "emp_code already exists")
    doc = body.model_dump()
    doc["created_at"] = datetime.now()
    db.employees.insert_one(doc)
    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(422, "page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(
            422,
            "page_size must be between 1 and 100"
        )

    query = {}

    if department:
        query["department"] = department

    total = db.employees.count_documents(query)

    items = list(
        db.employees.find(query, {"_id": 0})
        .sort("emp_code", 1)
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }




@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    ts_utc = (
        datetime.fromtimestamp(
            body.punched_at / 1000,
            tz=timezone.utc
        )
        if body.punched_at is not None
        else datetime.now(timezone.utc)
    )

    ts_ist = ts_utc.astimezone(IST)
    attendance_date = ts_ist.date().isoformat()

    existing = db.attendance_logs.find_one({
        "emp_code": body.emp_code,
        "date": attendance_date
    })

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Already punched in for this date"
        )

    shift_start = emp.get("shift_start", "09:30")

    


    late_minutes = compute_late_minutes(ts_utc, shift_start)

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts_utc.replace(tzinfo=None),
        "punch_out": None,
        "work_hours": None,
        "late_minutes": late_minutes,
        "overtime_minutes": 0,
        "half_day": False,
        "history": []
    }

    
    result = db.attendance_logs.insert_one(doc)
    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)

    return doc



@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to

    if status:
        q["status"] = status

    total = db.attendance_logs.count_documents(q)

    cursor = (
        db.attendance_logs.find(q)
        .sort([("date", -1), ("emp_code", 1)])
        .skip((page - 1) * page_size)
        .limit(page_size)
    )

    items = []
    for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }



class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None




@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    employee = db.employees.find_one({"emp_code": body.emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    ts_utc = (
        datetime.fromtimestamp(body.punched_at / 1000, tz=timezone.utc)
        if body.punched_at is not None
        else datetime.now(timezone.utc)
    )
    ts_ist = ts_utc.astimezone(IST)

    attendance_date = ts_ist.date().isoformat()
    yesterday = (ts_ist.date() - timedelta(days=1)).isoformat()

    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "date": {"$in": [attendance_date, yesterday]},
            "punch_in": {"$ne": None},
            "punch_out": None,
        },
        sort=[("date", -1)],
    )

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Open attendance record not found for this date",
        )

    punch_in_time = record["punch_in"]
    if punch_in_time.tzinfo is None:
        punch_in_utc = punch_in_time.replace(tzinfo=timezone.utc)
    else:
        punch_in_utc = punch_in_time.astimezone(timezone.utc)

    work_seconds = (ts_utc - punch_in_utc).total_seconds()
    if work_seconds < 0:
        raise HTTPException(
            status_code=422,
            detail="Punch-out cannot be before punch-in",
        )

    from decimal import Decimal, ROUND_HALF_UP

    work_hours = float(
        Decimal(str(work_seconds / 3600)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )

    start_h, start_m = map(
        int, employee.get("shift_start", "09:30").split(":")
    )
    end_h, end_m = map(
        int, employee.get("shift_end", "18:30").split(":")
    )

    shift_end = datetime.fromisoformat(record["date"]).replace(
        hour=end_h,
        minute=end_m,
        second=0,
        microsecond=0,
        tzinfo=IST,
    )

    if (end_h, end_m) <= (start_h, start_m):
        shift_end += timedelta(days=1)

    overtime_raw = int((ts_ist - shift_end).total_seconds() // 60)
    overtime_minutes = overtime_raw if overtime_raw >= 30 else 0
    half_day = Decimal(str(work_hours)) < Decimal("4.50")

    db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": {
                "punch_out": ts_utc.replace(tzinfo=None),
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated["id"] = str(updated.pop("_id"))
    return updated


@app.patch("/attendance/{emp_code}/{date}")
def update_attendance(emp_code: str, date: str, body: dict):
    from datetime import datetime, timezone
    from decimal import Decimal, ROUND_HALF_UP

    # Required regularization fields
    reason = body.get("reason")
    regularized_by = body.get("regularized_by")

    if not isinstance(reason, str) or not reason.strip():
        raise HTTPException(status_code=422, detail="reason is required")

    if not isinstance(regularized_by, str) or not regularized_by.strip():
        raise HTTPException(status_code=422, detail="regularized_by is required")

    # Only these attendance fields can be edited
    allowed_fields = {"status", "punch_in", "punch_out"}
    required_fields = {"reason", "regularized_by"}
    invalid_fields = set(body.keys()) - allowed_fields - required_fields

    if invalid_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Fields cannot be edited: {', '.join(sorted(invalid_fields))}"
        )

    requested = {key: body[key] for key in allowed_fields if key in body}

    if not requested:
        raise HTTPException(
            status_code=422,
            detail="Provide status, punch_in, or punch_out"
        )

    # Validate the date
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")

    record = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": date}
    )

    if not record:
        raise HTTPException(status_code=404, detail="Attendance record not found")

    # Convert epoch milliseconds to UTC-naive datetimes
    converted = {}

    for field, value in requested.items():
        if field == "status":
            if value not in {"PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"}:
                raise HTTPException(status_code=422, detail="Invalid attendance status")
            converted[field] = value
        else:
            if value is None:
                converted[field] = None
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} must be epoch milliseconds or null"
                )
            else:
                try:
                    converted[field] = datetime.fromtimestamp(
                        value / 1000, tz=timezone.utc
                    ).replace(tzinfo=None, microsecond=0)
                except (ValueError, OverflowError, OSError):
                    raise HTTPException(
                        status_code=422,
                        detail=f"Invalid epoch milliseconds for {field}"
                    )

    # Record only fields that actually changed
    actual_changes = {}

    for field, new_value in converted.items():
        old_value = record.get(field)
        if old_value != new_value:
            actual_changes[field] = {
                "from": old_value,
                "to": new_value
            }

    if not actual_changes:
        raise HTTPException(status_code=422, detail="No actual changes to apply")

    
    # Recalculate derived fields if punch times changed
    punch_in = converted.get("punch_in", record.get("punch_in"))
    punch_out = converted.get("punch_out", record.get("punch_out"))

    update_values = {
        field: change["to"]
        for field, change in actual_changes.items()
    }

    employee = db.employees.find_one({"emp_code": emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Recalculate work hours and half-day status
    if punch_in is not None and punch_out is not None:
        seconds = (punch_out - punch_in).total_seconds()

        if seconds < 0:
            raise HTTPException(
                status_code=422,
                detail="punch_out cannot precede punch_in",
            )

        work_hours = float(
            Decimal(str(seconds / 3600)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        )

        update_values["work_hours"] = work_hours
        update_values["half_day"] = work_hours < 4.50
    elif "punch_in" in converted or "punch_out" in converted:
        update_values["work_hours"] = None
        update_values["half_day"] = False

    # Recalculate late minutes when punch-in changes
    if "punch_in" in converted:
        update_values["late_minutes"] = (
            compute_late_minutes(
                punch_in.replace(tzinfo=timezone.utc),
                employee.get("shift_start", "09:30"),
            )
            if punch_in is not None
            else 0
        )

    # Recalculate overtime when punch-out changes
    if "punch_out" in converted:
        if punch_out is None:
            update_values["overtime_minutes"] = 0
        else:
            punch_out_ist = punch_out.replace(
                tzinfo=timezone.utc
            ).astimezone(IST)

            start_h, start_m = map(
                int, employee.get("shift_start", "09:30").split(":")
            )
            end_h, end_m = map(
                int, employee.get("shift_end", "18:30").split(":")
            )

            shift_end_ist = datetime.strptime(
                date, "%Y-%m-%d"
            ).replace(
                hour=end_h,
                minute=end_m,
                second=0,
                microsecond=0,
                tzinfo=IST,
            )

            if (end_h, end_m) <= (start_h, start_m):
                shift_end_ist += timedelta(days=1)

            overtime_minutes = int(
                (punch_out_ist - shift_end_ist).total_seconds() // 60
            )

            update_values["overtime_minutes"] = (
                overtime_minutes if overtime_minutes >= 30 else 0
            )


    # Save a complete manual-correction history entry
    history_entry = {
        "at": datetime.now(timezone.utc).replace(tzinfo=None),
        "by": regularized_by.strip(),
        "reason": reason.strip(),
        "changes": actual_changes,
    }

    db.attendance_logs.update_one(
        {"_id": record["_id"]},
        {
            "$set": update_values,
            "$push": {"history": history_entry},
        },
    )

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated["id"] = str(updated.pop("_id"))
    return updated


import traceback
print("MONTHLY ANALYTICS CODE LOADED", flush=True)
@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    import re
    from decimal import Decimal, ROUND_HALF_UP

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format",
        )

    employee = db.employees.find_one({"emp_code": emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    year, month_num = map(int, month.split("-"))
    month_start = f"{month}-01"

    if month_num == 12:
        next_month = f"{year + 1}-01-01"
    else:
        next_month = f"{year}-{month_num + 1:02d}-01"

    month_end = (
        datetime.strptime(next_month, "%Y-%m-%d").date()
        - timedelta(days=1)
    ).isoformat()

    # Count weekdays from the later of the join date and month start.
    first_work_date = max(employee["joined_on"], month_start)
    working_days = 0

    if first_work_date <= month_end:
        day = datetime.strptime(first_work_date, "%Y-%m-%d").date()
        last_day = datetime.strptime(month_end, "%Y-%m-%d").date()

        while day <= last_day:
            if day.weekday() < 5:
                working_days += 1
            day += timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": first_work_date,
                    "$lt": next_month,
                },
            }
        },
        {
            "$set": {
                "_is_weekday": {
                    "$in": [
                        {
                            "$dayOfWeek": {
                                "$dateFromString": {
                                    "dateString": "$date"
                                }
                            }
                        },
                        [2, 3, 4, 5, 6],
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_is_weekday",
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "total_overtime_minutes": {
                    "$sum": {"$ifNull": ["$overtime_minutes", 0]}
                },
            }
        },
    ]

    try:
        results = list(db.attendance_logs.aggregate(pipeline))
    
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Monthly analytics failed: {repr(e)}"
        )

    stats = results[0] if results else {}

    present_days = float(stats.get("present_days", 0))
    attendance_pct = None

    
    if working_days > 0:
        attendance_pct = float(
            (
                Decimal(str(present_days)) * Decimal("100")
                / Decimal(working_days)
            ).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP,
            )
        )


    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": stats.get("leave_days", 0),
        "late_count": stats.get("late_count", 0),
        "total_late_minutes": stats.get("total_late_minutes", 0),
        "total_overtime_minutes": stats.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct,
    }


@app.get("/analytics/departments/summary")
def department_summary(month: str, department: Optional[str] = None):
    import re
    from decimal import Decimal, ROUND_HALF_UP

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format",
        )

    year, month_num = map(int, month.split("-"))
    month_start = f"{month}-01"

    if month_num == 12:
        next_month = f"{year + 1}-01-01"
    else:
        next_month = f"{year}-{month_num + 1:02d}-01"

    month_end = (
        datetime.strptime(next_month, "%Y-%m-%d").date()
        - timedelta(days=1)
    ).isoformat()

    employee_match = {"joined_on": {"$lte": month_end}}
    if department is not None:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"employee_code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$employee_code"]},
                                    {"$gte": ["$date", month_start]},
                                    {"$lt": ["$date", next_month]},
                                ]
                            }
                        }
                    },
                    {
                        "$set": {
                            "_is_weekday": {
                                "$in": [
                                    {
                                        "$dayOfWeek": {
                                            "$dateFromString": {
                                                "dateString": "$date"
                                            }
                                        }
                                    },
                                    [2, 3, 4, 5, 6],
                                ]
                            }
                        }
                    },
                ],
                "as": "logs",
            }
        },
        {
            "$unwind": {
                "path": "$logs",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$addToSet": "$emp_code"},
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$eq": ["$logs._is_weekday", True]},
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$logs.half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "avg_work_hours": {
                    "$avg": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {"$ne": ["$logs.work_hours", None]},
                                ]
                            },
                            "$logs.work_hours",
                            None,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$logs.late_minutes", 0]}, 0]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$logs.late_minutes", 0]}
                },
                "leave_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "on_duty_count": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$logs.status", "ON_DUTY"]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"_id": 1}},
    ]

    try:
        results = list(db.employees.aggregate(pipeline))
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Department summary aggregation failed",
        )

    def round_half_up(value, places=2):
        if value is None:
            return None
        quantum = Decimal("1").scaleb(-places)
        return float(
            Decimal(str(value)).quantize(
                quantum, rounding=ROUND_HALF_UP
            )
        )

    items = []
    for result in results:
        headcount = len(result["headcount"])

        if headcount == 0:
            continue

        items.append({
            "department": result["_id"],
            "headcount": headcount,
            "present_days": round_half_up(result["present_days"]),
            "avg_work_hours": round_half_up(result.get("avg_work_hours")),
            "late_count": result["late_count"],
            "total_late_minutes": result["total_late_minutes"],
            "leave_count": result["leave_count"],
            "on_duty_count": result["on_duty_count"],
        })

    return {"month": month, "items": items}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str,
    limit: int = 10,
    department: Optional[str] = None
):
    import re
    from datetime import date
    from fastapi import HTTPException

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    if limit < 1 or limit > 50:
        raise HTTPException(
            status_code=422,
            detail="limit must be between 1 and 50"
        )

    year, month_num = map(int, month.split("-"))
    month_start = f"{month}-01"

    if month_num == 12:
        next_month = f"{year + 1}-01-01"
    else:
        next_month = f"{year}-{month_num + 1:02d}-01"

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": month_start,
                    "$lt": next_month
                },
                "late_minutes": {"$gt": 0}
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1}
            }
        },
        {
            "$match": {"total_late_minutes": {"$gt": 0}}
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"}
    ]

    if department is not None:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$sort": {
                "total_late_minutes": -1,
                "_id": 1
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        }
    ])

    try:
        items = list(db.attendance_logs.aggregate(pipeline))
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Late leaderboard aggregation failed"
        )

    return {
        "month": month,
        "items": items
    }

@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to")
):
    from datetime import date, timedelta
    from decimal import Decimal, ROUND_HALF_UP
    from fastapi import HTTPException

    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="'from' and 'to' must be valid YYYY-MM-DD dates"
        )

    if end < start:
        raise HTTPException(status_code=422, detail="'to' must not be before 'from'")

    days = (end - start).days + 1
    if days > 92:
        raise HTTPException(status_code=422, detail="Date range cannot exceed 92 days")

    employees = list(db.employees.find(
        {"department": department},
        {"_id": 0, "emp_code": 1, "joined_on": 1}
    ))
    if not employees:
        raise HTTPException(status_code=404, detail="Department not found")

    dates = [
        (start + timedelta(days=i)).isoformat()
        for i in range(days)
    ]

    pipeline = [
        {"$match": {
            "department": department,
            "joined_on": {"$lte": end.isoformat()}
        }},
        {"$project": {
            "_id": 0,
            "emp_code": 1,
            "joined_on": 1
        }},
        {"$group": {
            "_id": None,
            "employees": {"$push": "$$ROOT"}
        }},
        {"$project": {
            "_id": 0,
            "days": {
                "$map": {
                    "input": dates,
                    "as": "day",
                    "in": {
                        "date": "$$day",
                        "employees": {
                            "$filter": {
                                "input": "$employees",
                                "as": "employee",
                                "cond": {
                                    "$lte": ["$$employee.joined_on", "$$day"]
                                }
                            }
                        }
                    }
                }
            }
        }},
        {"$unwind": "$days"},
        {"$replaceRoot": {"newRoot": "$days"}},
        {"$set": {
            "is_working_day": {
                "$in": [
                    {"$dayOfWeek": {
                        "$dateFromString": {"dateString": "$date"}
                    }},
                    [2, 3, 4, 5, 6]
                ]
            },
            "headcount": {"$size": "$employees"},
            "codes": {
                "$map": {
                    "input": "$employees",
                    "as": "employee",
                    "in": "$$employee.emp_code"
                }
            }
        }},
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"day": "$date", "codes": "$codes"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$date", "$$day"]},
                    {"$in": ["$emp_code", "$$codes"]}
                ]}}},
                {"$project": {
                    "_id": 0, "status": 1,
                    "half_day": 1, "late_minutes": 1
                }}
            ],
            "as": "logs"
        }},
        {"$set": {
            "present_count": {
                "$sum": {
                    "$map": {
                        "input": {
                            "$filter": {
                                "input": "$logs",
                                "as": "log",
                                "cond": {
                                    "$in": [
                                        "$$log.status",
                                        ["PRESENT", "WFH", "ON_DUTY"]
                                    ]
                                }
                            }
                        },
                        "as": "log",
                        "in": {
                            "$cond": [
                                {"$eq": ["$$log.half_day", True]},
                                0.5,
                                1
                            ]
                        }
                    }
                }
            },
            "late_count": {
                "$size": {
                    "$filter": {
                        "input": "$logs",
                        "as": "log",
                        "cond": {
                            "$gt": [
                                {"$ifNull": ["$$log.late_minutes", 0]},
                                0
                            ]
                        }
                    }
                }
            }
        }},
        {"$set": {
            "attendance_rate": {
                "$cond": [
                    {"$and": [
                        "$is_working_day",
                        {"$gt": ["$headcount", 0]}
                    ]},
                    {"$divide": ["$present_count", "$headcount"]},
                    None
                ]
            }
        }},
        {"$setWindowFields": {
            "sortBy": {"date": 1},
            "output": {
                "moving_avg_7d": {
                    "$avg": "$attendance_rate",
                    "window": {"documents": [-6, 0]}
                }
            }
        }},
        {"$project": {
            "_id": 0,
            "date": 1,
            "is_working_day": 1,
            "headcount": 1,
            "present_count": 1,
            "late_count": 1,
            "attendance_rate": 1,
            "moving_avg_7d": 1
        }}
    ]

    try:
        items = list(db.employees.aggregate(pipeline))
    except Exception:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Department trend aggregation failed; check the terminal"
        )

    def round_rate(value):
        if value is None:
            return None
        return float(Decimal(str(value)).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP
        ))

    for item in items:
        item["attendance_rate"] = round_rate(item["attendance_rate"])
        item["moving_avg_7d"] = round_rate(item["moving_avg_7d"])
        item["present_count"] = float(item["present_count"])

    return {"department": department, "items": items}


from fastapi import HTTPException


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: str):
    allowed_endpoints = {
        "attendance": {
            "date": {
                "$gte": "2026-10-01",
                "$lt": "2026-11-01",
            }
        },
        "employee_attendance": {
            "emp_code": "EMP0001",
            "date": {
                "$gte": "2026-10-01",
                "$lt": "2026-11-01",
            },
        },
    }

    if endpoint not in allowed_endpoints:
        raise HTTPException(
            status_code=404,
            detail="Unknown endpoint. Use attendance or employee_attendance.",
        )

    query = allowed_endpoints[endpoint]

    try:
        result = db.attendance_logs.database.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": query,
            },
            verbosity="executionStats",
        )

        return {
            "endpoint": endpoint,
            "query": query,
            "executionStats": result.get("executionStats", {}),
            "queryPlanner": result.get("queryPlanner", {}),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Explain failed: {str(exc)}",
        )



# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #
