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
SENIOR_ROLE_PATTERN = re.compile(
    r"\b(?:senior|lead|principal|staff|director|manager|head of)\b",
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


def parse_we_work_remotely(response, source):
    feed = feedparser.parse(response.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"{source} returned an invalid RSS feed")
    jobs = []
    for entry in feed.entries:
        content = " ".join(
            [entry.get("summary", "")]
            + [item.get("value", "") for item in entry.get("content", [])]
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
    blocked_domains = (
        "weworkremotely.com",
        "remoteok.com",
        "remotive.com",
        "jobicy.com",
        "arbeitnow.com",
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
    )
    application_domains = (
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "workable.com",
        "smartrecruiters.com",
        "myworkdayjobs.com",
        "jobvite.com",
        "icims.com",
    )
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


def is_ai_role(title):
    return bool(AI_ROLE_PATTERN.search(title))


def job_experience_group(title, description, seniority):
    text = " ".join((title, description, seniority))
    if not is_fresher_experience(title, description, seniority):
        return "experienced" if re.search(r"\b\d+\+?\s*(?:years?|yrs?)\b", text, re.IGNORECASE) else "unknown"
    if FRESHER_ROLE_PATTERN.search(text):
        return "fresher"
    return "junior"


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
        return parsed.strftime("%Y-%m-%d")
    except (OverflowError, OSError, TypeError, ValueError):
        return str(value)


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
    return f"""🚀 NEW FRESHER AI/ML JOB

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
"""


def process_job(job, source, sent_urls, path=DB_PATH):
    title = job["title"]
    if not is_ai_role(title):
        return False, False
    senior_role = bool(
        SENIOR_ROLE_PATTERN.search(title)
        or SENIOR_ROLE_PATTERN.search(job.get("seniority", ""))
    )

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
    experience_group = (
        "experienced"
        if senior_role
        else job_experience_group(title, job["summary"], job.get("seniority", ""))
    )
    eligible_for_alert = (
        not senior_role
        and experience_group in {"fresher", "junior"}
        and remote_status == "fully_remote"
        and india_eligible
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
    try:
        send_telegram_message(build_alert(job_record, analysis, application_url))
    except RuntimeError as error:
        print(f"Telegram job alert failed for {title}: {error}")
        return is_new, False

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


if __name__ == "__main__":
    result = run_global_job_engine()
    print(
        "Global job collection complete: "
        f'{result["new_eligible"]} new alerts; '
        f'{result["sources_checked"]} sources checked; '
        f'{len(result["issues"])} collection/processing issues'
    )
