import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from career_engine import DB_PATH, connect_database, create_application, initialize_database


DASHBOARD_PATH = Path(__file__).resolve().with_name("dashboard.html")
APPLICATION_STATUSES = {"Saved", "Applied", "Interview", "Rejected", "Offer"}


@asynccontextmanager
async def lifespan(_app):
    initialize_database()
    yield


app = FastAPI(title="Vishes AI Career Intelligence", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApplicationUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
    follow_up_date: Optional[str] = None
    interview_notes: Optional[str] = None


def like_contains(value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def query(sql, parameters=()):
    connection = connect_database(DB_PATH)
    try:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
    finally:
        connection.close()


@app.get("/")
def dashboard():
    if not DASHBOARD_PATH.exists():
        raise HTTPException(status_code=404, detail="Dashboard file is missing")
    return FileResponse(DASHBOARD_PATH)


@app.get("/health")
def health():
    query("SELECT 1 AS ok")
    return {"status": "ok"}


@app.get("/summary")
def summary():
    def count(sql):
        return query(sql)[0]["count"]

    return {
        "jobs": count("SELECT COUNT(*) AS count FROM jobs"),
        "alerts": count("SELECT COUNT(*) AS count FROM jobs WHERE notified_at IS NOT NULL"),
        "news": count("SELECT COUNT(*) AS count FROM news"),
        "applications": count("SELECT COUNT(*) AS count FROM applications"),
    }


@app.get("/jobs")
def jobs(
    limit: int = 100,
    location: str = "",
    minimum_score: int = 0,
    experience_level: str = "",
    remote_status: str = "",
    india_eligibility: str = "",
):
    return query(
        """
        SELECT * FROM jobs
        WHERE score >= ?
          AND (? = '' OR lower(location) LIKE lower(?) ESCAPE '\\')
          AND (? = '' OR experience_level = ?)
          AND (? = '' OR remote_status = ?)
          AND (? = '' OR india_eligibility = ?)
        ORDER BY score DESC, created_at DESC
        LIMIT ?
        """,
        (
            minimum_score,
            location,
            like_contains(location),
            experience_level,
            experience_level,
            remote_status,
            remote_status,
            india_eligibility,
            india_eligibility,
            min(max(limit, 1), 500),
        ),
    )


@app.get("/news")
def news(limit: int = 50):
    return query(
        """
        SELECT * FROM news
        ORDER BY importance DESC, COALESCE(published_at, created_at) DESC
        LIMIT ?
        """,
        (min(max(limit, 1), 200),),
    )


@app.get("/applications")
def applications():
    return query(
        """
        SELECT applications.*, jobs.title, jobs.company, jobs.application_url,
               jobs.listing_url, jobs.location, jobs.experience_level, jobs.score
        FROM applications JOIN jobs ON jobs.id = applications.job_id
        ORDER BY applications.id DESC
        """
    )


@app.post("/applications/{job_id}")
def save_application(job_id: int):
    if not query("SELECT id FROM jobs WHERE id = ?", (job_id,)):
        raise HTTPException(status_code=404, detail="Job not found")
    application_id = create_application(job_id)
    return {"status": "Saved", "job_id": job_id, "application_id": application_id}


@app.patch("/applications/{application_id}")
def update_application(application_id: int, payload: ApplicationUpdate):
    if payload.status not in APPLICATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {sorted(APPLICATION_STATUSES)}",
        )
    assignments = ["status = ?"]
    parameters = [payload.status]
    if payload.notes is not None:
        assignments.append("notes = ?")
        parameters.append(payload.notes)
    if payload.follow_up_date is not None:
        assignments.append("follow_up_date = ?")
        parameters.append(payload.follow_up_date)
    if payload.interview_notes is not None:
        assignments.append("interview_notes = ?")
        parameters.append(payload.interview_notes)
    assignments.append(
        "application_date = CASE "
        "WHEN ? = 'Applied' THEN COALESCE(application_date, date('now')) "
        "ELSE application_date END"
    )
    parameters.extend([payload.status, application_id])
    connection = connect_database(DB_PATH)
    try:
        cursor = connection.execute(
            f"UPDATE applications SET {', '.join(assignments)} WHERE id = ?",
            parameters,
        )
        updated = cursor.rowcount
        connection.commit()
    finally:
        connection.close()
    if updated == 0:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"status": payload.status, "application_id": application_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
