<<<<<<< Updated upstream
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import certifi
import feedparser
import requests
from bs4 import BeautifulSoup

from career_engine import (
    DB_PATH,
    has_job_alerted,
    initialize_database,
    is_fresher_experience,
    is_fully_remote,
    india_eligibility_status,
    mark_job_alerted,
    normalize_text,
    normalize_url,
    record_collection_run,
    save_job,
    score_job,
)
from telegram_utils import send_telegram_message


BASE_DIR = Path(__file__).resolve().parent

SENT_JOBS_PATH = BASE_DIR / "sent_jobs.json"
USER_AGENT = "VishesCareerBot/1.0"
SOURCE_SPECS = (
    ("We Work Remotely", "rss", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("Remote OK", "remoteok", "https://remoteok.com/api"),
    ("Himalayas", "himalayas", "https://himalayas.app/jobs/api?limit=100"),
    ("Remotive", "remotive", "https://remotive.com/api/remote-jobs?limit=100"),
    ("Jobicy", "jobicy", "https://jobicy.com/api/v2/remote-jobs?count=100"),
    ("Arbeitnow", "arbeitnow", "https://www.arbeitnow.com/api/job-board-api"),
)
SOURCE_LIMITATIONS = {
    "Working Nomads": "Not integrated: the probed public RSS URL returned HTTP 404; no replacement feed/API was verified.",
    "Remote.co": "Not integrated: the public feed probe timed out; no stable public API/feed was verified.",
}

AI_ROLE_PATTERN = re.compile(
    r"\b(?:ai|ml|llm|genai|mlo?ps|machine learning|artificial intelligence|"
    r"deep learning|data scientist|data science|nlp|computer vision|"
    r"prompt engineer|ai trainer)\b",
    re.IGNORECASE,
)
FRESHER_ROLE_PATTERN = re.compile(
    r"\b(?:fresher|graduate|new grad|entry[- ]level|intern)\b",
    re.IGNORECASE,
)


def request_source(url):
    last_error = None
    for attempt in range(3):
        try:
            response = requests.get(
                url,
                timeout=20,
                headers={"Accept": "application/json, application/rss+xml, application/xml, text/xml"},
                verify=certifi.where(),
            )
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch source after 3 attempts: {last_error}")
=======
import certifi
import feedparser
import os
import requests
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from bs4 import BeautifulSoup
from career_engine import (
    initialize_database,
    is_known_job,
    normalize_url,
    score_job,
    save_job,
)
from dotenv import load_dotenv
from urllib.parse import urljoin, urlparse


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

missing_telegram_config = [
    name
    for name, value in (("BOT_TOKEN", BOT_TOKEN), ("CHAT_ID", CHAT_ID))
    if not value
]
if missing_telegram_config:
    raise SystemExit(
        "Missing Telegram configuration: "
        + ", ".join(missing_telegram_config)
        + ". Set these in the repository .env file or GitHub Actions secrets."
    )

SENT_JOBS_PATH = BASE_DIR / "sent_jobs.json"

if SENT_JOBS_PATH.exists():
    with SENT_JOBS_PATH.open(encoding="utf-8") as file:
        sent_jobs = json.load(file)
    if not isinstance(sent_jobs, list) or any(not isinstance(link, str) for link in sent_jobs):
        raise ValueError(f"{SENT_JOBS_PATH} must contain a JSON array of URL strings")
else:
    sent_jobs = []

sent_job_urls = {normalize_url(link) for link in sent_jobs}


initialize_database()
>>>>>>> Stashed changes


def html_text(value):
    return normalize_text(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))


def source_job(
    title,
    description,
    link,
    source,
    company="",
    location="",
    location_restrictions="",
    remote=True,
    salary="",
    published="",
    closing="",
    seniority="",
):
    if not title or not link:
        return None
    return {
        "title": normalize_text(title),
        "summary": html_text(description),
        "link": link,
        "source": source,
        "company": normalize_text(company),
        "location": location,
        "location_restrictions": location_restrictions,
        "remote": remote,
        "salary": normalize_text(salary),
        "published": published,
        "closing": closing,
        "seniority": normalize_text(seniority),
    }


<<<<<<< Updated upstream
def parse_we_work_remotely(response, source):
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"{source} returned an invalid RSS feed")
    jobs = []
    for entry in feed.entries:
        content = " ".join(
            [entry.get("summary", "")]
            + [item.get("value", "") for item in entry.get("content", [])]
=======
        response=requests.post(
            url,
            data=data,
            timeout=15,
            verify=certifi.where()
>>>>>>> Stashed changes
        )
        item = source_job(
            entry.get("title", ""),
            content,
            entry.get("link", ""),
            source,
            published=entry.get("published", ""),
            closing=entry.get("expirationDate") or entry.get("deadline") or "",
            remote=True,
        )
        if item:
            jobs.append(item)
    return jobs

<<<<<<< Updated upstream
=======
        response.raise_for_status()
        result=response.json()
>>>>>>> Stashed changes

def parse_remote_ok(response, source):
    data = response.json()
    if not isinstance(data, list):
        raise ValueError("Remote OK returned an unexpected response")
    jobs = []
    for item in data:
        if not isinstance(item, dict) or not item.get("position"):
            continue
        summary = " ".join(
            [item.get("description", "")]
            + [str(tag) for tag in item.get("tags", [])]
        )
        job = source_job(
            item.get("position"),
            summary,
            item.get("url", ""),
            source,
            company=item.get("company", ""),
            location=item.get("location", ""),
            remote=True,
            salary=item.get("salary", ""),
            published=item.get("date") or item.get("epoch") or "",
            closing=item.get("expiration_date") or item.get("deadline") or "",
        )
        if job:
            jobs.append(job)
    return jobs


def parse_himalayas(response, source):
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("Himalayas returned an unexpected response")
    jobs = []
    for item in data["jobs"]:
        job = source_job(
            item.get("title", ""),
            item.get("description", ""),
            item.get("applicationLink", ""),
            source,
            company=item.get("companyName", ""),
            location_restrictions=item.get("locationRestrictions", []),
            remote=True,
            salary=" ".join(
                str(value)
                for value in (item.get("minSalary"), item.get("maxSalary"), item.get("currency"))
                if value
            ),
            seniority=item.get("seniority", ""),
            published=(
                item.get("pubDate")
                or item.get("publishedAt")
                or item.get("createdAt")
                or item.get("datePosted")
                or ""
            ),
            closing=(
                item.get("expirationDate")
                or item.get("expiresAt")
                or item.get("validThrough")
                or item.get("applicationDeadline")
                or item.get("deadline")
                or ""
            ),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_remotive(response, source):
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("Remotive returned an unexpected response")
    jobs = []
    for item in data["jobs"]:
        job = source_job(
            item.get("title", ""),
            item.get("description", ""),
            item.get("url", ""),
            source,
            company=item.get("company_name", ""),
            location=item.get("candidate_required_location", ""),
            remote=True,
            salary=item.get("salary", ""),
            published=item.get("publication_date", ""),
            closing=item.get("expiration_date") or item.get("deadline") or "",
        )
        if job:
            jobs.append(job)
    return jobs


def parse_jobicy(response, source):
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("Jobicy returned an unexpected response")
    jobs = []
    for item in data["jobs"]:
        job = source_job(
            item.get("jobTitle") or item.get("title", ""),
            item.get("jobDescription") or item.get("jobExcerpt") or item.get("description", ""),
            item.get("url") or item.get("jobUrl") or item.get("applicationLink", ""),
            source,
            company=item.get("companyName") or item.get("company", ""),
            location=item.get("jobGeo") or item.get("location") or item.get("geo", ""),
            remote=True,
            salary=item.get("annualSalary") or item.get("salary", ""),
            published=(
                item.get("pubDate")
                or item.get("publishedAt")
                or item.get("datePosted")
                or item.get("createdAt")
                or ""
            ),
            closing=(
                item.get("expirationDate")
                or item.get("expiresAt")
                or item.get("validThrough")
                or item.get("applicationDeadline")
                or item.get("deadline")
                or ""
            ),
        )
        if job:
            jobs.append(job)
    return jobs


def parse_arbeitnow(response, source):
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("Arbeitnow returned an unexpected response")
    jobs = []
    for item in data["data"]:
        description = " ".join(
            [item.get("description", "")]
            + [str(tag) for tag in item.get("tags", [])]
        )
        job = source_job(
            item.get("title", ""),
            description,
            item.get("url", ""),
            source,
            company=item.get("company_name", ""),
            location=item.get("location", ""),
            remote=item.get("remote"),
            salary=item.get("salary", ""),
            published=item.get("created_at", ""),
            closing=(
                item.get("expiration_date")
                or item.get("expires_at")
                or item.get("valid_through")
                or item.get("deadline")
                or ""
            ),
        )
        if job:
            jobs.append(job)
    return jobs


SOURCE_PARSERS = {
    "rss": parse_we_work_remotely,
    "remoteok": parse_remote_ok,
    "himalayas": parse_himalayas,
    "remotive": parse_remotive,
    "jobicy": parse_jobicy,
    "arbeitnow": parse_arbeitnow,
}


def fetch_source_jobs(source, source_type, url):
    response = request_source(url)
    return SOURCE_PARSERS[source_type](response, source)


def get_application_link(job_url):
<<<<<<< Updated upstream
    blocked_domains = (
        "weworkremotely.com",
        "remoteok.com",
        "remotive.com",
        "jobicy.com",
        "arbeitnow.com",
=======

    blocked_domains=(
        "weworkremotely.com",
        "remoteok.com",
>>>>>>> Stashed changes
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
    )
<<<<<<< Updated upstream
    application_domains = (
=======

    application_domains=(
>>>>>>> Stashed changes
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "workable.com",
        "smartrecruiters.com",
        "myworkdayjobs.com",
        "jobvite.com",
        "icims.com",
    )
<<<<<<< Updated upstream
    application_words = (
        "apply",
        "application",
        "apply now",
        "apply for this job",
        "start application",
        "submit application",
    )
    try:
        response = request_source(job_url)
    except (requests.RequestException, RuntimeError) as error:
        print(f"Application link lookup failed: {error}")
=======

    application_words=(
        "apply",
        "application",
        "start application",
        "apply now",
        "apply for this job",
        "submit application",
    )

    def is_blocked(url):

        hostname=urlparse(url).hostname or ""

        hostname=hostname.lower().removeprefix("www.")

        return any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in blocked_domains
        )

    def candidate_score(url, label):

        if not url.startswith(("http://", "https://")):

            return -1

        if is_blocked(url):

            return -1

        hostname=(urlparse(url).hostname or "").lower()

        score=0

        if any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in application_domains
        ):

            score+=100

        if any(word in label for word in application_words):

            score+=80

        if any(
            word in url.lower()
            for word in ("apply", "application", "careers", "jobs")
        ):

            score+=20

        return score

    try:

        response=requests.get(
            job_url,
            timeout=10,
            headers={
                "User-Agent":"Mozilla/5.0"
            },
            verify=certifi.where()
        )

        soup=BeautifulSoup(response.text,"html.parser")

        candidates=[]

        for link in soup.find_all("a",href=True):

            full_url=urljoin(job_url,link["href"])

            label=" ".join(
                value
                for value in (
                    link.get_text(" ",strip=True),
                    link.get("aria-label",""),
                    link.get("title",""),
                )
                if value
            ).lower()

            score=candidate_score(full_url,label)

            if score >= 80:

                candidates.append((score,full_url))

        if candidates:

            candidates.sort(key=lambda candidate: candidate[0],reverse=True)

            return candidates[0][1]


>>>>>>> Stashed changes
        return job_url

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []
    for link in soup.find_all("a", href=True):
        full_url = urljoin(job_url, link["href"])
        hostname = (urlparse(full_url).hostname or "").lower().removeprefix("www.")
        if not full_url.startswith(("http://", "https://")):
            continue
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in blocked_domains):
            continue
        label = " ".join(
            value
            for value in (
                link.get_text(" ", strip=True),
                link.get("aria-label", ""),
                link.get("title", ""),
            )
            if value
        ).lower()
        score = 0
        if any(
            hostname == domain or hostname.endswith(f".{domain}")
            for domain in application_domains
        ):
            score += 100
        if any(word in label for word in application_words):
            score += 80
        if any(word in full_url.lower() for word in ("apply", "application", "careers", "jobs")):
            score += 20
        if score >= 80:
            candidates.append((score, full_url))
    candidates.sort(key=lambda candidate: candidate[0], reverse=True)
    return candidates[0][1] if candidates else job_url


<<<<<<< Updated upstream
def is_ai_role(title):
    return bool(AI_ROLE_PATTERN.search(title))
=======
def get_himalayas_jobs():

    try:

        url="https://himalayas.app/jobs/api?limit=20"

        response=requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent":"Mozilla/5.0"
            },
            verify=certifi.where()
        )

        data=response.json()

        jobs=[]


        for job in data.get("jobs",[]):

            title=job.get("title","")

            description=job.get("description","")

            job_link=job.get("applicationLink","")

            company=job.get("companyName","")

            seniority=job.get("seniority","")

            min_salary=job.get("minSalary")

            max_salary=job.get("maxSalary")

            currency=job.get("currency","")

            location_restrictions=job.get(
                "locationRestrictions",
                []
            )

            published = (
                job.get("pubDate")
                or job.get("publishedAt")
                or job.get("createdAt")
                or job.get("datePosted")
                or ""
            )
            closing = (
                job.get("expirationDate")
                or job.get("expiresAt")
                or job.get("validThrough")
                or job.get("applicationDeadline")
                or job.get("deadline")
                or ""
            )

            jobs.append({

                "title":title,

                "summary":description,

                "link":job_link,

                "company":company,

                "seniority":seniority,

                "min_salary":min_salary,

                "max_salary":max_salary,

                "currency":currency,

                "location_restrictions":location_restrictions,

                "published":published,

                "closing":closing

            })


        return jobs


    except Exception as msg:

        print("Himalayas error:",msg)

        return []


def get_remote_ok_jobs():
>>>>>>> Stashed changes


def job_experience_group(title, description, seniority):
    text = " ".join((title, description, seniority))
    if not is_fresher_experience(title, description, seniority):
        return "experienced" if re.search(r"\b\d+\+?\s*(?:years?|yrs?)\b", text, re.IGNORECASE) else "unknown"
    if FRESHER_ROLE_PATTERN.search(text):
        return "fresher"
    return "junior"

<<<<<<< Updated upstream

def remote_status_for(job):
    description = job["summary"]
    location = job.get("location", "")
    text = f"{description} {location}"
    if re.search(
        r"\b(?:hybrid|part(?:ly|ially) remote|remote (?:is )?(?:optional|an option)|"
        r"days in (?:the )?office)\b",
        text,
        re.IGNORECASE,
    ):
        return "hybrid"
    if re.search(r"\b(?:on[- ]?site|office[- ]based|in[- ]office)\b", text, re.IGNORECASE):
        return "onsite"
    remote = is_fully_remote(
        job["title"],
        description,
        location,
        remote=job.get("remote"),
    )
    if remote:
        return "fully_remote"
    return "unknown"


def india_category(job, remote_status, india_eligible):
    location_text = normalize_text(
        " ".join(
            [
                str(job.get("location", "") or ""),
                str(job.get("location_restrictions", "") or ""),
            ]
        )
    ).lower()
    if "india" not in location_text and not india_eligible:
        return "unknown"
    if remote_status == "fully_remote":
        return "India Remote"
    if re.search(r"\bhybrid\b", job["summary"] + " " + location_text, re.IGNORECASE):
        return "India Hybrid"
    if re.search(r"\bon[- ]?site|in[- ]office|office[- ]based\b", job["summary"] + " " + location_text, re.IGNORECASE):
        return "India Onsite"
    return "unknown"


def format_job_date(value):
    if not value:
        return "Not provided"
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d")
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(str(value))
=======
        response=requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent":"Mozilla/5.0"
            },
            verify=certifi.where()
        )

        data=response.json()

        jobs=[]


        for job in data:

            if not isinstance(job,dict):

                continue


            if "position" not in job:

                continue


            title=job.get("position","")

            description=job.get("description","")

            job_link=job.get("url","")


            jobs.append({

                "title":title,

                "summary":description,

                "link":job_link,

                "published":job.get("date") or job.get("epoch") or "",

                "closing":job.get("expiration_date") or job.get("deadline") or ""

            })


        return jobs


    except Exception as msg:

        print("Remote OK error:",msg)

        return []


def get_remotive_jobs():

    try:

        url="https://remotive.com/api/remote-jobs?limit=20"

        response=requests.get(
            url,
            timeout=15,
            headers={
                "User-Agent":"Mozilla/5.0"
            },
            verify=certifi.where()
        )

        data=response.json()

        jobs=[]

        for job in data.get("jobs",[]):

            jobs.append({

                "title":job.get("title",""),

                "summary":job.get("description",""),

                "link":job.get("url",""),

                "company":job.get("company_name",""),

                "location":job.get("candidate_required_location",""),

                "salary":job.get("salary",""),

                "published":job.get("publication_date",""),

                "closing":job.get("expiration_date") or job.get("deadline") or ""

            })

        return jobs


    except Exception as msg:

        print("Remotive error:",msg)

        return []


def get_jobicy_jobs():
    """Fetch recent remote jobs from Jobicy's public API (no API key)."""
    try:
        response = requests.get(
            "https://jobicy.com/api/v2/remote-jobs",
            params={"count": 100},
            timeout=20,
            headers={"Accept": "application/json", "User-Agent": "VishesCareerBot/1.0"},
            verify=certifi.where(),
        )
        response.raise_for_status()
        data = response.json()
        jobs = []
        for item in data.get("jobs", []):
            title = item.get("jobTitle") or item.get("title") or ""
            link = item.get("url") or item.get("jobUrl") or item.get("applicationLink") or ""
            description = item.get("jobDescription") or item.get("jobExcerpt") or item.get("description") or ""
            if not title or not link:
                continue
            jobs.append({
                "title": title,
                "summary": description,
                "link": link,  # Preserve Jobicy's canonical listing URL/source attribution.
                "company": item.get("companyName") or item.get("company") or "",
                "location": item.get("jobGeo") or item.get("location") or item.get("geo") or "Remote",
                "salary": item.get("annualSalary") or item.get("salary") or "",
                "published": (
                    item.get("pubDate")
                    or item.get("publishedAt")
                    or item.get("datePosted")
                    or item.get("createdAt")
                    or ""
                ),
                "closing": (
                    item.get("expirationDate")
                    or item.get("expiresAt")
                    or item.get("validThrough")
                    or item.get("applicationDeadline")
                    or item.get("deadline")
                    or ""
                ),
            })
        return jobs
    except (requests.RequestException, ValueError) as error:
        print(f"Jobicy error: {error}")
        return []


def get_arbeitnow_jobs():
    """Fetch public listings from Arbeitnow's job-board API."""
    try:
        response = requests.get(
            "https://www.arbeitnow.com/api/job-board-api",
            timeout=20,
            headers={"Accept": "application/json", "User-Agent": "VishesCareerBot/1.0"},
            verify=certifi.where(),
        )
        response.raise_for_status()
        data = response.json()
        jobs = []
        for item in data.get("data", []):
            title = item.get("title", "")
            link = item.get("url", "")
            if not title or not link:
                continue
            tags = item.get("tags", []) or []
            description = item.get("description", "")
            if tags:
                description = f"{description} {' '.join(str(tag) for tag in tags)}"
            jobs.append({
                "title": title,
                "summary": description,
                "link": link,
                "company": item.get("company_name", ""),
                "location": item.get("location", ""),
                "salary": item.get("salary", ""),
                "published": item.get("created_at", ""),
                "closing": (
                    item.get("expiration_date")
                    or item.get("expires_at")
                    or item.get("valid_through")
                    or item.get("deadline")
                    or ""
                ),
            })
        return jobs
    except (requests.RequestException, ValueError) as error:
        print(f"Arbeitnow error: {error}")
        return []


job_sources=[

    {
        "name":"We Work Remotely",
        "type":"rss",
        "url":"https://weworkremotely.com/categories/remote-programming-jobs.rss"
    },

    {
        "name":"Remote OK",
        "type":"api",
        "url":"https://remoteok.com/api"
    },

    {
        "name":"Himalayas",
        "type":"himalayas",
        "url":"https://himalayas.app/jobs/api"
    },

    {
        "name":"Remotive",
        "type":"remotive",
        "url":"https://remotive.com/api/remote-jobs?limit=20"
    },

    {
        "name":"Jobicy",
        "type":"jobicy",
        "url":"https://jobicy.com/api/v2/remote-jobs?count=100"
    },

    {
        "name":"Arbeitnow",
        "type":"arbeitnow",
        "url":"https://www.arbeitnow.com/api/job-board-api"
    }

]


ai_title_keywords=[

    "ai engineer",
    "artificial intelligence engineer",
    "ml engineer",
    "machine learning engineer",
    "ai/ml engineer",
    "ai / ml engineer",
    "deep learning engineer",
    "nlp engineer",
    "natural language processing engineer",
    "computer vision engineer",
    "mlops engineer",
    "genai engineer",
    "generative ai engineer",
    "llm engineer",
    "ai researcher",
    "machine learning researcher",
    "ai trainer",
    "prompt engineer",
    "prompt engineering",
    "data scientist",
    "machine learning scientist",
    "ai scientist"

]


ai_technology_keywords=[

    "rag",
    "retrieval augmented generation",
    "agentic ai",
    "large language model",
    "llm",
    "generative ai",
    "genai",
    "machine learning",
    "deep learning",
    "pytorch",
    "tensorflow",
    "computer vision",
    "natural language processing"

]


entry_keywords=[

    "junior",
    "entry level",
    "entry-level",
    "fresher",
    "graduate",
    "new grad",
    "0-1 years",
    "0-2 years",
    "0–1 years",
    "0–2 years",
    "will train",
    "no experience",
    "no prior experience"

]


senior_keywords=[

    "senior",
    "lead",
    "principal",
    "staff",
    "director",
    "manager",
    "head of"

]

def format_job_date(value):
    if not value:
        return "Not provided by source"
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                parsed = parsedate_to_datetime(str(value))
>>>>>>> Stashed changes
        return parsed.strftime("%Y-%m-%d")
    except (OverflowError, OSError, TypeError, ValueError):
        return str(value)


<<<<<<< Updated upstream
def format_salary(job, analysis):
    if job.get("salary"):
        return normalize_text(job["salary"])
    salary = analysis["salary"]
    if salary["min"] is None:
        return "Not specified"
    return (
        f'{salary["currency"]} {salary["min"]:,.0f}-{salary["max"]:,.0f} '
        f'{salary["period"]}'.strip()
    )


def load_sent_jobs():
    if not SENT_JOBS_PATH.exists():
        return set()
    with SENT_JOBS_PATH.open(encoding="utf-8") as file:
        values = json.load(file)
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError(f"{SENT_JOBS_PATH} must contain a JSON array of URL strings")
    return {normalize_url(value) for value in values}


def append_sent_job(job_url):
    urls = load_sent_jobs()
    normalized_url = normalize_url(job_url)
    if normalized_url and normalized_url not in urls:
        urls.add(normalized_url)
        with SENT_JOBS_PATH.open("w", encoding="utf-8") as file:
            json.dump(sorted(urls), file, indent=4)


def build_alert(job, analysis, application_url):
    return f"""🚀 NEW ELIGIBLE FRESHER/JUNIOR AI/ML JOB

💼 Role: {job["title"]}
🏢 Company: {job.get("company") or "Not specified"}
📡 Source: {job["source"]}
🎯 Experience: {analysis["experience"]}
🤖 Skills: {" • ".join(analysis["skills"]) or "Not specified"}
🌍 Work: 100% Remote — India Eligible
📅 Posted: {format_job_date(job.get("published"))} | ⏳ Deadline: {format_job_date(job.get("closing"))}
💰 Salary: {format_salary(job, analysis)}
⭐ Match Score: {analysis["score"]}/100
✅ Company Verified: Unverified
🔗 Apply URL (not independently verified): {application_url}
=======
for source in job_sources:

    source_name=source["name"]

    source_url=source["url"]

    print("CHECKING:",source_name)


    if source["type"]=="rss":

        feed=feedparser.parse(source_url)

        jobs=[
            {
                **entry,
                "published": entry.get("published", ""),
                "closing": entry.get("expirationDate") or entry.get("deadline") or "",
            }
            for entry in feed.entries
        ]


    elif source["type"]=="api":

        jobs=get_remote_ok_jobs()


    elif source["type"]=="himalayas":

        jobs=get_himalayas_jobs()


    elif source["type"]=="remotive":

        jobs=get_remotive_jobs()

    elif source["type"]=="jobicy":

        jobs=get_jobicy_jobs()

    elif source["type"]=="arbeitnow":

        jobs=get_arbeitnow_jobs()


    else:

        jobs=[]


    print("Jobs found:",len(jobs))


    for job in jobs:

        title=job.get("title","").lower()

        description=job.get("summary","").lower()

        text=title+" "+description

        company=job.get("company","")

        job_link=normalize_url(job.get("link",""))

        analysis=score_job(
            job.get("title",""),
            job.get("summary",""),
            company,
            job.get("location","") or job.get("location_restrictions",""),
            job.get("salary","")
        )

        if not company:

            analysis["dedupe_key"]="url:"+job_link


        is_ai=False

        is_entry=False

        is_senior=False

        matched_keywords=[]


        for keyword in ai_title_keywords:

            if keyword in title:

                is_ai=True

                matched_keywords.append(keyword)


        for keyword in ai_technology_keywords:

            if keyword in title:

                is_ai=True

                matched_keywords.append(keyword)


        for keyword in entry_keywords:

            if keyword in text:

                is_entry=True

                break


        for keyword in senior_keywords:

            if keyword in title:

                is_senior=True

                break


        if is_ai and not is_senior:

            job_title=job.get("title","")


            if not job_link:

                continue


            if job_link in sent_job_urls or is_known_job(analysis["dedupe_key"]):

                print("ALREADY SENT - SKIPPING")

                print("Job:",job_title)

                print("--------------------")

                continue


            matched_keywords=list(
                dict.fromkeys(matched_keywords)
            )


            if source_name in {"Himalayas", "Jobicy", "Arbeitnow"}:

                # Keep the source's canonical job page; avoid guessing a third-party apply URL.
                application_link=job_link

            else:

                application_link=get_application_link(
                    job_link
                )

            normalized_job=dict(job)

            normalized_job.update({
                "source":source_name,
                "link":job_link,
                "application_link":application_link,
                "analysis":analysis
            })

            salary=analysis["salary"]

            salary_text="Not specified"

            if salary["min"] is not None:

                salary_text=(
                    f'{salary["currency"]} '
                    f'{salary["min"]:,.0f}-{salary["max"]:,.0f} '
                    f'{salary["period"]}'.strip()
                )


            print("MATCH FOUND")

            print("Source:",source_name)

            print("Job:",job_title)

            print("AI/ML:",True)

            print("AI Keywords:",matched_keywords)

            print("Entry Level:",is_entry)

            print("Match Score:",analysis["score"])

            print("Link:",job_link)

            print("Application Link:",application_link)

            print("--------------------")


            message=f"""🚀 NEW REMOTE AI/ML JOB

Source: {source_name}

Job:
{job_title}

🤖 AI/ML:
{", ".join(matched_keywords)}

🎯 Entry Level:
{"YES" if is_entry else "Not specified"}

🧠 Skills:
{" • ".join(analysis["skills"]) or "Not specified"}

🎯 Experience:
{analysis["experience"]}

📅 Posted:
{format_job_date(job.get("published"))}

⏳ Apply by:
{format_job_date(job.get("closing"))}

🌍 Location:
{analysis["location"]}

💰 Salary:
{salary_text}

⭐ Match:
{analysis["match"]} ({analysis["score"]}/100)

🔗 Apply:
{application_link}
>>>>>>> Stashed changes
"""


def process_job(job, source, sent_urls, path=DB_PATH):
    title = job["title"]
    if not is_ai_role(title):
        return False, False

    link = normalize_url(job.get("link", ""))
    if not link:
        return False, False

    remote_status = remote_status_for(job)
    india_status = india_eligibility_status(
        job["summary"],
        job.get("location", ""),
        job.get("location_restrictions", ""),
    )
    india_eligible = india_status == "eligible"
    experience_group = job_experience_group(
        title, job["summary"], job.get("seniority", "")
    )
    eligible_for_alert = (
        experience_group in {"fresher", "junior"}
        and remote_status == "fully_remote"
        and india_status == "eligible"
    )
    analysis = score_job(
        title,
        f'{job["summary"]} {job.get("seniority", "")}',
        job.get("company", ""),
        job.get("location") or job.get("location_restrictions", ""),
        job.get("salary", ""),
        india_eligible=india_eligible,
    )
    if not job.get("company"):
        analysis["dedupe_key"] = "url:" + link

    job_record = {
        **job,
        "source": source,
        "link": link,
        "application_link": job.get("application_link", ""),
        "remote_status": remote_status,
        "india_eligibility": india_status,
        "employment_category": india_category(job, remote_status, india_eligible),
        "experience_group": experience_group,
        "company_verification": "Unverified",
        "application_verified": False,
        "analysis": analysis,
    }
    is_new = save_job(job_record, path)

    if not eligible_for_alert or has_job_alerted(analysis["dedupe_key"], path):
        return is_new, False
    if link in sent_urls:
        mark_job_alerted(analysis["dedupe_key"], path)
        return is_new, False

    application_url = get_application_link(link)
    job_record["application_link"] = application_url
    save_job(job_record, path)
    send_telegram_message(build_alert(job_record, analysis, application_url))

    mark_job_alerted(analysis["dedupe_key"], path)
    append_sent_job(link)
    sent_urls.add(link)
    return is_new, True


def run_global_job_engine(path=DB_PATH):
    initialize_database(path)
    sent_urls = load_sent_jobs()
    totals = {"new_eligible": 0, "unique_jobs": 0, "sources_checked": 0, "issues": []}
    for source, source_type, url in SOURCE_SPECS:
        print(f"Checking {source}")
        try:
            jobs = fetch_source_jobs(source, source_type, url)
        except (
            requests.RequestException,
            RuntimeError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
        ) as error:
            message = f"{source}: {error}"
            print(f"Collection failed: {message}")
            totals["issues"].append(message)
            record_collection_run("jobs", source, False, error=message, path=path)
            continue

<<<<<<< Updated upstream
        totals["sources_checked"] += 1
        new_count = 0
        alert_count = 0
        processing_issues = []
        for job in jobs:
            if not is_ai_role(job["title"]):
                continue
            try:
                is_new, alerted = process_job(job, source, sent_urls, path)
            except (
                requests.RequestException,
                RuntimeError,
                ValueError,
                sqlite3.Error,
                KeyError,
                TypeError,
                AttributeError,
                OSError,
            ) as error:
                message = f"{source} job processing failed: {error}"
                totals["issues"].append(message)
                processing_issues.append(message)
                print(message)
                continue
            new_count += int(is_new)
            alert_count += int(alerted)
        totals["new_eligible"] += alert_count
        totals["unique_jobs"] += new_count
        record_collection_run(
            "jobs",
            source,
            not processing_issues,
            items=len(jobs),
            error="; ".join(processing_issues),
            path=path,
        )
        print(f"{source}: fetched {len(jobs)}, new AI/ML listings {new_count}, alerts {alert_count}")
    return totals
=======
                save_job(normalized_job)

                sent_jobs.append(job_link)
                sent_job_urls.add(job_link)
>>>>>>> Stashed changes

                with SENT_JOBS_PATH.open("w", encoding="utf-8") as file:

<<<<<<< Updated upstream
if __name__ == "__main__":
    result = run_global_job_engine()
    print(
        "Global job collection complete: "
        f'{result["new_eligible"]} new alerts; '
        f'{result["sources_checked"]} sources checked; '
        f'{len(result["issues"])} collection/processing issues'
    )
    if result["issues"]:
        raise SystemExit(1)
=======
                    json.dump(
                        sent_jobs,
                        file,
                        indent=4
                    )

                print("SAVED TO sent_jobs.json")


            else:

                print(
                    "NOT SAVED - Telegram notification failed"
                )


            print("--------------------")
>>>>>>> Stashed changes
