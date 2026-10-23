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


def send_telegram(message):

    url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data={
        "chat_id":CHAT_ID,
        "text":message
    }

    try:

        response=requests.post(
            url,
            data=data,
            timeout=15,
            verify=certifi.where()
        )

        response.raise_for_status()
        result=response.json()

        print("Telegram:",result)

        if result.get("ok"):

            return True

        return False

    except Exception as msg:

        print("Telegram error:",msg)

        return False


def get_application_link(job_url):

    blocked_domains=(
        "weworkremotely.com",
        "remoteok.com",
        "linkedin.com",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
    )

    application_domains=(
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
        "workable.com",
        "smartrecruiters.com",
        "myworkdayjobs.com",
        "jobvite.com",
        "icims.com",
    )

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


        return job_url


    except Exception as msg:

        print("Application link error:",msg)

        return job_url


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

    try:

        url="https://remoteok.com/api"

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
        return parsed.strftime("%Y-%m-%d")
    except (OverflowError, OSError, TypeError, ValueError):
        return str(value)


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
"""


            telegram_sent=send_telegram(message)


            if telegram_sent:

                save_job(normalized_job)

                sent_jobs.append(job_link)
                sent_job_urls.add(job_link)

                with SENT_JOBS_PATH.open("w", encoding="utf-8") as file:

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