import re
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


INDIA_TIMEZONE = timezone(timedelta(hours=5, minutes=30))


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
    "SQL",
    "Git",
    "Linux",
    "NumPy",
    "Pandas",
    "scikit-learn",
    "Statistics",
    "Mathematics",
    "Machine Learning",
    "Deep Learning",
    "PyTorch",
    "TensorFlow",
    "NLP",
    "Computer Vision",
    "LLMs",
    "RAG",
    "AI Agents",
    "LangChain",
    "Hugging Face",
    "FastAPI",
    "REST APIs",
    "Docker",
    "Kubernetes",
    "MLflow",
    "MLOps",
    "AWS",
    "Azure",
    "GCP",
    "Spark",
    "Kafka",
    "Airflow",
    "Java",
    "C++",
    "JavaScript",
    "TypeScript",
    "React",
    "PostgreSQL",
    "MongoDB",
    "Redis",
    "Data Engineering",
    "Data Analysis",
    "Generative AI",
    "Prompt Engineering",
)

SKILL_ALIASES = {
    "Python": (r"\bpython\b",),
    "SQL": (r"\bsql\b",),
    "Git": (r"\bgit(?:hub|lab)?\b",),
    "Linux": (r"\blinux\b",),
    "NumPy": (r"\bnumpy\b",),
    "Pandas": (r"\bpandas\b",),
    "scikit-learn": (r"\bscikit[- ]learn\b", r"\bsklearn\b"),
    "Statistics": (r"\bstatistics?\b", r"\bstatistical analysis\b"),
    "Mathematics": (r"\bmathematics?\b", r"\blinear algebra\b", r"\bcalculus\b"),
    "Machine Learning": (r"\bmachine learning\b", r"\bml\b"),
    "Deep Learning": (r"\bdeep learning\b",),
    "PyTorch": (r"\bpytorch\b",),
    "TensorFlow": (r"\btensorflow\b",),
    "NLP": (r"\bnlp\b", r"\bnatural language processing\b"),
    "Computer Vision": (r"\bcomputer vision\b",),
    "LLMs": (r"\bllms?\b", r"\blarge language models?\b"),
    "RAG": (r"\brag\b", r"\bretrieval[- ]augmented generation\b"),
    "AI Agents": (r"\bai agents?\b", r"\bagentic ai\b", r"\bagentic workflows?\b"),
    "LangChain": (r"\blangchain\b",),
    "Hugging Face": (r"\bhugging ?face\b",),
    "FastAPI": (r"\bfastapi\b",),
    "REST APIs": (r"\brest(?:ful)? apis?\b", r"\bapi development\b"),
    "Docker": (r"\bdocker\b",),
    "Kubernetes": (r"\bkubernetes\b", r"\bk8s\b"),
    "MLflow": (r"\bmlflow\b",),
    "MLOps": (r"\bmlops\b",),
    "AWS": (r"\baws\b", r"\bamazon web services\b"),
    "Azure": (r"\bazure\b", r"\bmicrosoft azure\b"),
    "GCP": (r"\bgcp\b", r"\bgoogle cloud(?: platform)?\b"),
    "Spark": (r"\bapache spark\b", r"\bpyspark\b", r"\bspark\b"),
    "Kafka": (r"\bapache kafka\b", r"\bkafka\b"),
    "Airflow": (r"\bapache airflow\b", r"\bairflow\b"),
    "Java": (r"\bjava\b",),
    "C++": (r"\bc\+\+\b",),
    "JavaScript": (r"\bjavascript\b", r"\bjs\b"),
    "TypeScript": (r"\btypescript\b",),
    "React": (r"\breact(?:\.js)?\b",),
    "PostgreSQL": (r"\bpostgres(?:ql)?\b",),
    "MongoDB": (r"\bmongodb\b",),
    "Redis": (r"\bredis\b",),
    "Data Engineering": (r"\bdata engineering\b",),
    "Data Analysis": (r"\bdata analysis\b", r"\bdata analytics\b"),
    "Generative AI": (r"\bgenerative ai\b", r"\bgenai\b"),
    "Prompt Engineering": (r"\bprompt engineering\b",),
}

EXPERIENCE_PATTERNS = (
    ("fresher", ("fresher", "new grad", "graduate", "no experience", "entry level", "entry-level")),
    ("0-1 years", ("0-1 years", "0–1 years", "0 to 1 year", "less than 1 year")),
    ("0-2 years", ("0-2 years", "0–2 years", "0 to 2 years")),
    ("1-2 years", ("1-2 years", "1–2 years", "1 to 2 years")),
)

ENTRY_LEVEL_PATTERN = re.compile(
    r"\b(?:fresher|freshers|new[- ]grad(?:uate)?s?|graduates?|junior|entry[- ]level|"
    r"no (?:prior )?experience)\b",
    re.IGNORECASE,
)
EXPERIENCE_RANGE_PATTERN = re.compile(
    r"\b(?P<minimum>\d+)\s*(?:-|–|to)\s*(?P<maximum>\d+)\s*"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)
EXPERIENCE_NUMBER_PATTERN = re.compile(
    r"\b(?P<years>\d+)(?P<plus>\+)?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
EXPERIENCE_WORD_NUMBER_PATTERN = re.compile(
    r"\b(?:three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s*"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)
EXPERIENCE_OVER_TWO_PATTERN = re.compile(
    r"\b(?:more than|over|in excess of|greater than)\s+(?:2|two)\s*"
    r"(?:years?|yrs?)\b",
    re.IGNORECASE,
)
UP_TO_TWO_YEARS_PATTERN = re.compile(
    r"\b(?:up to|maximum of|no more than|less than)\s+2\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
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
    range_match = EXPERIENCE_RANGE_PATTERN.search(lowered)
    if range_match:
        return f'{range_match.group("minimum")}-{range_match.group("maximum")} years'

    years = EXPERIENCE_NUMBER_PATTERN.search(lowered)
    if years and int(years.group("years")) > 2:
        plus = "+" if years.group("plus") else ""
        return f'{years.group("years")}{plus} years'

    for label, patterns in EXPERIENCE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return label
    if UP_TO_TWO_YEARS_PATTERN.search(lowered):
        return "0-2 years"
    if years:
        plus = "+" if years.group("plus") else ""
        return f'{years.group("years")}{plus} years'
    return "Not specified"


def is_fresher_experience(title, description="", seniority=""):
    text = normalize_text(
        " ".join(normalize_text(value) for value in (title, description, seniority))
    )
    if not text:
        return False
    if re.search(
        r"\bnot\s+(?:(?:a|an)\s+)?(?:fresher|entry[- ]level)\b|"
        r"\bnot suitable for (?:freshers?|graduates?|entry[- ]level)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    if EXPERIENCE_OVER_TWO_PATTERN.search(text):
        return False

    for match in EXPERIENCE_RANGE_PATTERN.finditer(text):
        if int(match.group("maximum")) > 2:
            return False

    for match in EXPERIENCE_WORD_NUMBER_PATTERN.finditer(text):
        if not text[match.end():match.end() + 8].lower().startswith(" ago"):
            return False

    for match in EXPERIENCE_NUMBER_PATTERN.finditer(text):
        years = int(match.group("years"))
        if years > 2 or (years == 2 and match.group("plus")):
            following_text = text[match.end():match.end() + 8].lower()
            if not following_text.startswith(" ago"):
                return False

    if ENTRY_LEVEL_PATTERN.search(text):
        if (
            re.search(
                r"\bgraduates?\s+(?:degree|studies|program|qualification)\b",
                text,
                re.IGNORECASE,
            )
            and not re.search(
                r"\b(?:fresher|new[- ]grad(?:uate)?|junior|entry[- ]level|no (?:prior )?experience)\b",
                text,
                re.IGNORECASE,
            )
        ):
            return False
        return True

    return bool(EXPERIENCE_RANGE_PATTERN.search(text)) or bool(
        UP_TO_TWO_YEARS_PATTERN.search(text)
    ) or bool(
        re.search(
            r"\b(?:0|1|2)(?:\+)?\s*(?:years?|yrs?)\s+"
            r"(?:of\s+)?(?:relevant\s+)?experience\b",
            text,
            re.IGNORECASE,
        )
    )


def is_fully_remote(title, description="", location="", remote=None):
    if isinstance(location, (list, tuple)):
        location = " ".join(normalize_text(value) for value in location)
    text = normalize_text(
        " ".join(normalize_text(value) for value in (title, description, location))
    )
    lowered = text.lower()
    if re.search(
        r"\b(?:hybrid|on[- ]?site|office[- ]based|in[- ]office|"
        r"part(?:ly|ially) remote|not (?:fully )?remote|"
        r"remote (?:is )?(?:optional|an option)|"
        r"days in (?:the )?office)\b",
        lowered,
    ):
        return False
    if isinstance(remote, str):
        remote_value = remote.strip().lower()
        if remote_value in {"false", "no", "0", "hybrid", "onsite", "on-site"}:
            return False
        if remote_value in {"true", "yes", "1", "remote", "fully remote"}:
            return True
    if remote is False:
        return False
    if remote is True:
        return True
    return bool(
        re.search(r"\bremote\b|work from home|fully distributed", lowered)
    )


def india_eligibility_status(description="", location="", location_restrictions=""):
    def location_text(value):
        if isinstance(value, (list, tuple)):
            return " ".join(normalize_text(item) for item in value)
        return normalize_text(value)

    structured_location = normalize_text(
        f"{location_text(location)} {location_text(location_restrictions)}"
    ).lower()
    description = normalize_text(description).lower()

    negative_patterns = (
        r"\b(?:not|excluding|except|outside)\s+(?:eligible\s+)?(?:for\s+)?india\b",
        r"\bindia\s+(?:is\s+)?(?:not eligible|excluded|unsupported|unavailable)\b",
        r"\b(?:not open|not available|not accepting)\s+(?:to\s+)?(?:applicants|candidates)?\s*(?:from|in)?\s*india\b",
        r"\bnot\s+(?:eligible|open|available|accepting)\b.{0,40}\bindia\b",
    )
    location_restriction_patterns = (
        r"\b(?:us|usa|united states|canada|uk|united kingdom|europe|eu|"
        r"australia|new zealand)\s+only\b",
        r"\bonly\s+(?:from|in|based in)\s+(?:the\s+)?"
        r"(?:us|usa|united states|canada|uk|united kingdom|europe|eu|"
        r"australia|new zealand)\b",
        r"\bmust be based in (?:the\s+)?"
        r"(?:us|usa|united states|canada|uk|united kingdom|europe|eu|"
        r"australia|new zealand)\b",
    )
    if any(
        re.search(pattern, text)
        for text in (structured_location, description)
        for pattern in negative_patterns + location_restriction_patterns
    ):
        return "ineligible"

    if re.search(r"\bindia\b|\bworldwide\b|\banywhere\b|\bglobal(?:ly)?\b", structured_location):
        return "eligible"

    india_acceptance_patterns = (
        r"\b(?:work|working|hire|hiring|applicants?|candidates?)\s+"
        r"(?:from\s+)?(?:anywhere|worldwide|anywhere in the world)\b",
        r"\b(?:remote\s+)?(?:work|working)\s+from\s+anywhere\b",
        r"\b(?:applicants?|candidates?)\s+(?:can|may)\s+be\s+"
        r"(?:based\s+)?(?:anywhere|worldwide)\b",
        r"\bopen to (?:applicants?|candidates?)\s+(?:anywhere|worldwide)\b",
        r"\b(?:based|located|residing|living)\s+in\s+india\b",
        r"\bwork(?:ing)?\s+from\s+india\b",
        r"\bindia[- ]based\b",
        r"\bindia\s+(?:eligible|only|accepted|allowed)\b",
        r"\b(?:hiring|recruiting)\s+(?:in|from)\s+india\b",
        r"\b(?:eligible|open|available|accepting)\s+(?:to\s+)?"
        r"(?:applicants|candidates|employees|workers|talent)?\s*"
        r"(?:from|in)?\s*india\b",
        r"\b(?:applicants|candidates|employees|workers|talent)\s+"
        r"(?:must be|should be|can be|based|located|residing|living)?\s*"
        r"(?:from|in)?\s*india\b",
    )
    if any(re.search(pattern, description) for pattern in india_acceptance_patterns):
        return "eligible"

    has_worldwide_scope = re.search(
        r"\b(?:worldwide|anywhere|global(?:ly)?)\b",
        structured_location,
    )
    has_restricted_region = re.search(
        r"\b(?:us|usa|u\.s\.|united states|canada|uk|united kingdom|"
        r"europe|eu|australia|new zealand)\b",
        structured_location,
    )
    if structured_location and (
        (has_restricted_region and not has_worldwide_scope)
        or not re.search(r"\b(?:remote|worldwide|anywhere|global)\b", structured_location)
    ):
        return "ineligible"
    return "unknown"


def is_india_eligible(description="", location="", location_restrictions=""):
    return india_eligibility_status(description, location, location_restrictions) == "eligible"


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
    return [
        skill
        for skill in SKILLS
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in SKILL_ALIASES[skill])
    ]


def dedupe_key(title, company=""):
    role = re.sub(r"[^a-z0-9]+", " ", normalize_text(title).lower()).strip()
    organization = re.sub(r"[^a-z0-9]+", " ", normalize_text(company).lower()).strip()
    return f"{organization}|{role}" if organization else f"|{role}"


def score_job(title, description, company="", location="", salary="", india_eligible=False):
    if isinstance(location, (list, tuple)):
        location = ", ".join(normalize_text(value) for value in location)
    text = " ".join((title, description))
    skills = extract_skills(text)
    score = min(40, len(skills) * 8)

    if re.search(
        r"\b(?:artificial intelligence|machine learning|ai|ml|llm|data scientist)\b",
        normalize_text(title),
        re.IGNORECASE,
    ):
        score += 30
    if is_fresher_experience(title, description):
        score += 15
    if india_eligible:
        score += 15

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
                remote_status TEXT NOT NULL DEFAULT 'unknown',
                india_eligibility TEXT NOT NULL DEFAULT 'unknown',
                employment_category TEXT NOT NULL DEFAULT 'unknown',
                experience_group TEXT NOT NULL DEFAULT 'unknown',
                company_verification TEXT NOT NULL DEFAULT 'Unverified',
                application_verified INTEGER NOT NULL DEFAULT 0,
                notified_at TEXT,
                last_seen_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS job_observations (
                job_id INTEGER NOT NULL,
                observed_date TEXT NOT NULL,
                is_new INTEGER NOT NULL DEFAULT 0,
                skills TEXT NOT NULL DEFAULT '',
                experience_group TEXT NOT NULL DEFAULT 'unknown',
                remote_status TEXT NOT NULL DEFAULT 'unknown',
                india_eligibility TEXT NOT NULL DEFAULT 'unknown',
                employment_category TEXT NOT NULL DEFAULT 'unknown',
                snapshot_version INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (job_id, observed_date),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
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
                category TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                engine TEXT NOT NULL,
                source TEXT NOT NULL,
                success INTEGER NOT NULL,
                items INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS daily_skill_metrics (
                report_date TEXT NOT NULL,
                group_name TEXT NOT NULL,
                skill TEXT NOT NULL,
                job_count INTEGER NOT NULL,
                unique_jobs INTEGER NOT NULL,
                PRIMARY KEY (report_date, group_name, skill)
            );
            CREATE TABLE IF NOT EXISTS daily_skill_combinations (
                report_date TEXT NOT NULL,
                group_name TEXT NOT NULL,
                skill_pair TEXT NOT NULL,
                job_count INTEGER NOT NULL,
                PRIMARY KEY (report_date, group_name, skill_pair)
            );
            CREATE TABLE IF NOT EXISTS daily_reports (
                report_date TEXT NOT NULL,
                report_type TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (report_date, report_type)
            );
            """
        )
        job_columns = {row[1] for row in connection.execute("PRAGMA table_info(jobs)")}
        job_migrations = {
            "closing_at": "TEXT",
            "remote_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "india_eligibility": "TEXT NOT NULL DEFAULT 'unknown'",
            "employment_category": "TEXT NOT NULL DEFAULT 'unknown'",
            "experience_group": "TEXT NOT NULL DEFAULT 'unknown'",
            "company_verification": "TEXT NOT NULL DEFAULT 'Unverified'",
            "application_verified": "INTEGER NOT NULL DEFAULT 0",
            "notified_at": "TEXT",
            "last_seen_at": "TEXT",
        }
        for column, definition in job_migrations.items():
            if column not in job_columns:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
        observation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(job_observations)")
        }
        observation_migrations = {
            "skills": "TEXT NOT NULL DEFAULT ''",
            "experience_group": "TEXT NOT NULL DEFAULT 'unknown'",
            "remote_status": "TEXT NOT NULL DEFAULT 'unknown'",
            "india_eligibility": "TEXT NOT NULL DEFAULT 'unknown'",
            "employment_category": "TEXT NOT NULL DEFAULT 'unknown'",
            "snapshot_version": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in observation_migrations.items():
            if column not in observation_columns:
                connection.execute(
                    f"ALTER TABLE job_observations ADD COLUMN {column} {definition}"
                )
        news_columns = {row[1] for row in connection.execute("PRAGMA table_info(news)")}
        if "content_hash" not in news_columns:
            connection.execute("ALTER TABLE news ADD COLUMN content_hash TEXT")
        if "digest_sent_at" not in news_columns:
            connection.execute("ALTER TABLE news ADD COLUMN digest_sent_at TEXT")
        if "category" not in news_columns:
            connection.execute("ALTER TABLE news ADD COLUMN category TEXT")
        connection.commit()
    finally:
        connection.close()


def save_job(job, path=DB_PATH):
    initialize_database(path)
    connection=sqlite3.connect(path)
    try:
        dedupe_key = job["analysis"]["dedupe_key"]
        listing_url = normalize_url(job.get("link", ""))
        application_url = normalize_url(job.get("application_link", ""))
        now = datetime.now(timezone.utc)
        local_date = now.astimezone(INDIA_TIMEZONE).date().isoformat()
        existing = connection.execute(
            """
            SELECT id, dedupe_key, skills
            FROM jobs
            WHERE dedupe_key = ?
               OR listing_url = NULLIF(?, '')
               OR listing_url = NULLIF(?, '')
               OR application_url = NULLIF(?, '')
               OR application_url = NULLIF(?, '')
            ORDER BY CASE WHEN dedupe_key = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (
                dedupe_key,
                listing_url,
                application_url,
                listing_url,
                application_url,
                dedupe_key,
            ),
        ).fetchone()
        if existing:
            dedupe_key = existing[1]
            job["analysis"]["dedupe_key"] = dedupe_key
            existing_skills = [skill.strip() for skill in (existing[2] or "").split(",") if skill.strip()]
            job["analysis"]["skills"] = list(
                dict.fromkeys(existing_skills + job["analysis"]["skills"])
            )
        location = job.get("location") or job.get("location_restrictions") or ""
        if isinstance(location, (list, tuple)):
            location = ", ".join(normalize_text(value) for value in location)
        location = normalize_text(location) or "Not specified"
        salary = normalize_text(job.get("salary", ""))
        salary_data = job["analysis"]["salary"]
        if not salary and salary_data.get("min") is not None:
            salary = (
                f'{salary_data["currency"]} {salary_data["min"]:,.0f}-'
                f'{salary_data["max"]:,.0f} {salary_data["period"]}'
            ).strip()
        connection.execute(
            """
            INSERT INTO jobs
            (dedupe_key, title, company, source, listing_url, application_url,
             location, experience, salary, skills, score, published_at, closing_at,
             remote_status, india_eligibility, employment_category, experience_group,
             company_verification, application_verified, last_seen_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dedupe_key) DO UPDATE SET
              application_url=COALESCE(NULLIF(excluded.application_url, ''), jobs.application_url),
              score=excluded.score,
              source=CASE
                WHEN instr('|' || jobs.source || '|', '|' || excluded.source || '|') > 0
                THEN jobs.source
                ELSE jobs.source || '|' || excluded.source
              END,
              location=CASE
                WHEN excluded.location = 'Not specified' THEN jobs.location
                ELSE excluded.location
              END,
              experience=CASE
                WHEN excluded.experience = 'Not specified' THEN jobs.experience
                ELSE excluded.experience
              END,
              salary=COALESCE(NULLIF(excluded.salary, ''), jobs.salary),
              skills=COALESCE(NULLIF(excluded.skills, ''), jobs.skills),
              remote_status=CASE
                WHEN excluded.remote_status = 'unknown' THEN jobs.remote_status
                ELSE excluded.remote_status
              END,
              india_eligibility=CASE
                WHEN excluded.india_eligibility = 'unknown' THEN jobs.india_eligibility
                ELSE excluded.india_eligibility
              END,
              employment_category=CASE
                WHEN excluded.employment_category = 'unknown' THEN jobs.employment_category
                ELSE excluded.employment_category
              END,
              experience_group=CASE
                WHEN excluded.experience_group = 'unknown' THEN jobs.experience_group
                ELSE excluded.experience_group
              END,
              last_seen_at=excluded.last_seen_at,
              published_at=COALESCE(NULLIF(jobs.published_at, ''), excluded.published_at),
              closing_at=COALESCE(NULLIF(jobs.closing_at, ''), excluded.closing_at)
            """,
            (
                job["analysis"]["dedupe_key"],
                job.get("title", ""),
                job.get("company", ""),
                job.get("source", ""),
                listing_url,
                application_url,
                location,
                job["analysis"]["experience"],
                salary,
                ", ".join(job["analysis"]["skills"]),
                job["analysis"]["score"],
                job.get("published", ""),
                job.get("closing", ""),
                job.get("remote_status", "unknown"),
                job.get("india_eligibility", "unknown"),
                job.get("employment_category", "unknown"),
                job.get("experience_group", "unknown"),
                job.get("company_verification", "Unverified"),
                int(bool(job.get("application_verified", False))),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        persisted = connection.execute(
            """
            SELECT id, skills, experience_group, remote_status,
                   india_eligibility, employment_category
            FROM jobs WHERE dedupe_key = ?
            """,
            (dedupe_key,),
        ).fetchone()
        job_id = persisted[0]
        is_new = existing is None
        connection.execute(
            """
            INSERT INTO job_observations
            (job_id, observed_date, is_new, skills, experience_group, remote_status,
             india_eligibility, employment_category, snapshot_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(job_id, observed_date) DO UPDATE SET
              skills=excluded.skills,
              experience_group=excluded.experience_group,
              remote_status=excluded.remote_status,
              india_eligibility=excluded.india_eligibility,
              employment_category=excluded.employment_category,
              snapshot_version=excluded.snapshot_version
            """,
            (
                job_id,
                local_date,
                int(is_new),
                persisted[1] or "",
                persisted[2] or "unknown",
                persisted[3] or "unknown",
                persisted[4] or "unknown",
                persisted[5] or "unknown",
            ),
        )
        connection.commit()
        return is_new
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


def has_job_alerted(dedupe_key, path=DB_PATH):
    initialize_database(path)
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT 1 FROM jobs WHERE dedupe_key = ? AND notified_at IS NOT NULL LIMIT 1",
            (dedupe_key,),
        ).fetchone()
    finally:
        connection.close()
    return row is not None


def mark_job_alerted(dedupe_key, path=DB_PATH):
    initialize_database(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE jobs SET notified_at = ? WHERE dedupe_key = ?",
            (datetime.now(timezone.utc).isoformat(), dedupe_key),
        )
        connection.commit()
    finally:
        connection.close()


def record_collection_run(engine, source, success, items=0, error="", path=DB_PATH):
    initialize_database(path)
    now = datetime.now(timezone.utc).isoformat()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            INSERT INTO collection_runs
            (engine, source, success, items, error, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (engine, source, int(bool(success)), items, error[:500], now, now),
        )
        connection.commit()
    finally:
        connection.close()


def create_application(job_id, path=DB_PATH):
    initialize_database(path)
    connection=sqlite3.connect(path)
    try:
        connection.execute("INSERT INTO applications (job_id) VALUES (?)", (job_id,))
        connection.commit()
    finally:
        connection.close()
