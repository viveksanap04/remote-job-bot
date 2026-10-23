import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from career_engine import DB_PATH, create_application, initialize_database


app = FastAPI(title="Vishes AI Career Intelligence")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    initialize_database()


def query(sql, parameters=()):
    connection = sqlite3.connect(DB_PATH)
    try:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(sql, parameters).fetchall()]
    finally:
        connection.close()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/jobs")
def jobs(limit: int = 100, location: str = "", minimum_score: int = 0):
    return query(
        """
        SELECT * FROM jobs
        WHERE score >= ? AND (? = '' OR lower(location) LIKE lower(?))
        ORDER BY score DESC, created_at DESC
        LIMIT ?
        """,
        (minimum_score, location, f"%{location}%", min(max(limit, 1), 500)),
    )


@app.get("/news")
def news(limit: int = 50):
    return query(
        "SELECT * FROM news ORDER BY importance DESC, published_at DESC LIMIT ?",
        (min(max(limit, 1), 200),),
    )


@app.get("/applications")
def applications():
    return query(
        """
        SELECT applications.*, jobs.title, jobs.company, jobs.application_url
        FROM applications JOIN jobs ON jobs.id = applications.job_id
        ORDER BY applications.id DESC
        """
    )


@app.post("/applications/{job_id}")
def save_application(job_id: int):
    if not query("SELECT id FROM jobs WHERE id = ?", (job_id,)):
        raise HTTPException(status_code=404, detail="Job not found")
    create_application(job_id)
    return {"status": "Saved", "job_id": job_id}


@app.patch("/applications/{application_id}")
def update_application(application_id: int, status: str, notes: str = "", follow_up_date: str = ""):
    allowed = {"Saved", "Applied", "Interview", "Rejected", "Offer"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(allowed)}")
    connection = sqlite3.connect(DB_PATH)
    try:
        cursor = connection.execute(
            """
            UPDATE applications
            SET status = ?, notes = ?, follow_up_date = ?,
                application_date = CASE WHEN ? = 'Applied' THEN COALESCE(application_date, date('now')) ELSE application_date END
            WHERE id = ?
            """,
            (status, notes, follow_up_date, status, application_id),
        )
        connection.commit()
    finally:
        connection.close()
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Application not found")
    return {"status": status, "application_id": application_id}


@app.get("/skills")
def skills():
    rows = query("SELECT skills FROM jobs WHERE skills != ''")
    counts = {}
    for row in rows:
        for skill in row["skills"].split(", "):
            counts[skill] = counts.get(skill, 0) + 1
    return sorted(
        ({"skill": skill, "demand": count} for skill, count in counts.items()),
        key=lambda item: item["demand"],
        reverse=True,
    )
