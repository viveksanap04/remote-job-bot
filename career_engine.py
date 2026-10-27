import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DB_PATH = "career_intelligence.db"

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
    "utm_campaign",
    "utm_medium",
    "utm_source",
    "utm_term",
}

SKILLS = (
    "Python",
    "PyTorch",
    "TensorFlow",
    "LLM",
    "RAG",
    "MLOps",
    "Docker",
    "Kubernetes",
    "FastAPI",
    "Hugging Face",
    "NLP",
    "Computer Vision",
    "SQL",
)


EXPERIENCE_PATTERNS = (
    ("fresher", ("fresher", "new grad", "graduate", "no experience", "entry level", "entry-level")),
    ("0-1 years", ("0-1 years", "0–1 years", "0 to 1 year", "less than 1 year")),
    ("0-2 years", ("0-2 years", "0–2 years", "0 to 2 years")),
    ("1-2 years", ("1-2 years", "1–2 years", "1 to 2 years")),
)


def normalize_url(url):
    """Remove tracking noise while preserving the actual job path and query."""
    if not url:
        return ""

    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_salary(text):
    text = normalize_text(text)
    pattern = re.compile(
        r"(?P<currency>[$€£₹]|USD|EUR|GBP|INR)?\s*"
        r"(?P<low>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?:-|–|to)\s*"
        r"(?:[$€£₹]|USD|EUR|GBP|INR)?\s*"
        r"(?P<high>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?P<period>/\s*(?:year|yr|month|mo)|\s*(?:per\s+year|per\s+month))?",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return {"min": None, "max": None, "currency": "", "period": ""}

    currency = (match.group("currency") or "").upper().replace("₹", "INR")
    period = normalize_text(match.group("period") or "")
    return {
        "min": float(match.group("low").replace(",", "")),
        "max": float(match.group("high").replace(",", "")),
        "currency": currency,
        "period": period,
    }


def detect_experience(text):
    lowered = normalize_text(text).lower()
    for label, patterns in EXPERIENCE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return label
    years = re.search(r"(?:at least|minimum of|\b)(\d+)\+?\s+years?", lowered)
    return f"{years.group(1)}+ years" if years else "Not specified"


def detect_location(text):
    lowered = normalize_text(text).lower()
    if "worldwide" in lowered or "anywhere" in lowered:
        return "Worldwide"
    if "india" in lowered or "indian" in lowered:
        return "India"
    if re.search(r"\b(us|usa|united states|u\.s\.)\b", lowered):
        return "US"
    if any(region in lowered for region in ("europe", "european union", "eu only")):
        return "Europe"
    if "remote" in lowered:
        return "Remote"
    return "Not specified"


def extract_skills(text):
    lowered = normalize_text(text).lower()
    return [skill for skill in SKILLS if skill.lower() in lowered]


def dedupe_key(title, company=""):
    role = re.sub(r"[^a-z0-9]+", " ", normalize_text(title).lower()).strip()
    organization = re.sub(r"[^a-z0-9]+", " ", normalize_text(company).lower()).strip()
    return f"{organization}|{role}" if organization else f"|{role}"


def score_job(title, description, company="", location="", salary=""):
    if isinstance(location, (list, tuple)):
        location = ", ".join(normalize_text(value) for value in location)
    text = " ".join((title, description, company, location, salary))
    lowered = text.lower()
    skills = extract_skills(text)
    score = min(100, len(skills) * 8)

    if any(term in lowered for term in ("artificial intelligence", "machine learning", "ai engineer", "ml engineer", "llm")):
        score += 35
    if any(term in lowered for term in ("junior", "entry", "fresher", "graduate", "new grad")):
        score += 15
    if detect_experience(text) != "Not specified":
        score += 10
    if detect_location(text) != "Not specified":
        score += 5

    score = min(100, score)
    return {
        "score": score,
        "match": "High" if score >= 70 else "Medium" if score >= 40 else "Low",
        "skills": skills,
        "experience": detect_experience(text),
        "location": detect_location(text),
        "salary": extract_salary(salary or description),
        "dedupe_key": dedupe_key(title, company),
    }


def initialize_database(path=DB_PATH):
    connection=sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                company TEXT,
                source TEXT,
                listing_url TEXT NOT NULL,
                application_url TEXT,
                location TEXT,
                experience TEXT,
                salary TEXT,
                skills TEXT,
                score INTEGER,
                published_at TEXT,
                closing_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Saved',
                application_date TEXT,
                notes TEXT,
                follow_up_date TEXT,
                interview_notes TEXT,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                source TEXT,
                summary TEXT,
                importance INTEGER DEFAULT 0,
                published_at TEXT,
                content_hash TEXT,
                digest_sent_at TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        job_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        if "closing_at" not in job_columns:
            connection.execute("ALTER TABLE jobs ADD COLUMN closing_at TEXT")
        news_columns = {row[1] for row in connection.execute("PRAGMA table_info(news)")}
        if "content_hash" not in news_columns:
            connection.execute("ALTER TABLE news ADD COLUMN content_hash TEXT")
        if "digest_sent_at" not in news_columns:
            connection.execute("ALTER TABLE news ADD COLUMN digest_sent_at TEXT")
        connection.commit()
    finally:
        connection.close()


def save_job(job, path=DB_PATH):
    initialize_database(path)
    connection=sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO jobs
            (dedupe_key, title, company, source, listing_url, application_url,
             location, experience, salary, skills, score, published_at, closing_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
              application_url=excluded.application_url,
              score=excluded.score,
              published_at=COALESCE(jobs.published_at, excluded.published_at),
              closing_at=COALESCE(jobs.closing_at, excluded.closing_at)
            """,
            (
                job["analysis"]["dedupe_key"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("source", ""),
                normalize_url(job.get("link", "")),
                normalize_url(job.get("application_link", "")),
                job["analysis"]["location"],
                job["analysis"]["experience"],
                job["analysis"]["salary"].get("currency", ""),
                ", ".join(job["analysis"]["skills"]),
                job["analysis"]["score"],
                job.get("published", ""),
                job.get("closing", ""),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()


def is_known_job(dedupe_key, path=DB_PATH):
    initialize_database(path)
    connection=sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT 1 FROM jobs WHERE dedupe_key = ? LIMIT 1",
            (dedupe_key,),
        ).fetchone()
    finally:
        connection.close()
    return row is not None


def create_application(job_id, path=DB_PATH):
    initialize_database(path)
    connection=sqlite3.connect(path)
    try:
        connection.execute("INSERT INTO applications (job_id) VALUES (?)", (job_id,))
        connection.commit()
    finally:
        connection.close()
