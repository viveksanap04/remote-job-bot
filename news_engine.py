import hashlib
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import certifi
import feedparser
import requests
from bs4 import BeautifulSoup

from career_engine import (
    DB_PATH,
    INDIA_TIMEZONE,
    initialize_database,
    normalize_text,
    normalize_url,
    record_collection_run,
)
from telegram_utils import send_telegram_message


NEWS_SOURCES = (
    ("OpenAI", "rss", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "rss", "https://deepmind.google/blog/rss.xml"),
    ("Anthropic", "web", "https://www.anthropic.com/news"),
    ("Hugging Face", "rss", "https://huggingface.co/blog/feed.xml"),
    ("NVIDIA", "rss", "https://developer.nvidia.com/blog/feed/"),
    ("Microsoft Research", "rss", "https://www.microsoft.com/en-us/research/feed/"),
    ("Google Research", "rss", "https://research.google/blog/rss/"),
    ("AWS Machine Learning", "rss", "https://aws.amazon.com/blogs/machine-learning/feed/"),
    ("arXiv CS.AI", "rss", "https://export.arxiv.org/rss/cs.AI"),
    ("arXiv ML", "rss", "https://export.arxiv.org/rss/cs.LG"),
    ("arXiv Computer Vision", "rss", "https://export.arxiv.org/rss/cs.CV"),
    ("arXiv Statistical ML", "rss", "https://export.arxiv.org/rss/stat.ML"),
)

IMPORTANT_TERMS = (
    "launch", "release", "model", "funding", "research", "open source",
    "breakthrough", "safety", "agent", "inference", "rag", "multimodal",
)
NEWS_TOPIC_PATTERN = re.compile(
    r"\b(?:ai|ml|llm|agentic|agents?|genai|transformer|multimodal|rag|mlops|"
    r"inference|computer vision|nlp)\b"
    r"|artificial intelligence|machine learning|deep learning|large language model"
    r"|computer vision|vision-language|neural network|generative ai|robotics|"
    r"retrieval[- ]augmented generation|natural language processing|"
    r"model serving|ai infrastructure|ai deployment",
    re.IGNORECASE,
)
STOP_WORDS = {"about", "after", "and", "from", "into", "that", "the", "this", "with", "your"}
IMPORTANT_NEWS_THRESHOLD = 44


def importance_score(title, summary):
    text = f"{title} {summary}".lower()
    return min(100, 20 + sum(8 for term in IMPORTANT_TERMS if term in text))


def topic_category(title, summary):
    text = f"{title} {summary}".lower()
    categories = (
        (
            "New Model Release",
            ("model release", "new model", "model launch", "introduces", "announces model"),
        ),
        ("Agentic AI Developments", ("agentic", "ai agent", "agents")),
        ("LLM and RAG Updates", ("llm", "large language model", "rag", "retrieval-augmented")),
        ("Open-Source AI Tools", ("open source", "open-source", "hugging face", "framework")),
        ("Computer Vision and Deep Learning", ("computer vision", "deep learning", "vision model")),
        ("Research Breakthrough", ("research", "paper", "study", "arxiv", "breakthrough")),
        ("AI Industry and Company Announcements", ("funding", "partnership", "acquisition", "company")),
    )
    return next(
        (category for category, terms in categories if any(term in text for term in terms)),
        "Breaking AI News",
    )


def content_tokens(title, summary):
    words = re.findall(r"[a-z0-9]{3,}", f"{title} {summary}".lower())
    return {word for word in words if word not in STOP_WORDS}


def content_hash(title, summary):
    tokens = " ".join(sorted(content_tokens(title, summary)))
    return hashlib.sha256(tokens.encode("utf-8")).hexdigest()


def is_same_story(title, summary, existing_title, existing_summary):
    incoming = content_tokens(title, summary)
    existing = content_tokens(existing_title, existing_summary)
    if not incoming or not existing:
        return False
    overlap = len(incoming & existing) / max(1, min(len(incoming), len(existing)))
    return overlap >= 0.72


def ensure_news_columns(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(news)")}
    if "content_hash" not in columns:
        connection.execute("ALTER TABLE news ADD COLUMN content_hash TEXT")
    if "digest_sent_at" not in columns:
        connection.execute("ALTER TABLE news ADD COLUMN digest_sent_at TEXT")
    if "category" not in columns:
        connection.execute("ALTER TABLE news ADD COLUMN category TEXT")
    if "notified_at" not in columns:
        connection.execute("ALTER TABLE news ADD COLUMN notified_at TEXT")


def parse_feed(source, response):
    feed = feedparser.parse(response.content)
    if feed.bozo:
        raise ValueError(f"{source} returned an invalid RSS feed")
    entries = [
        {
            "url": entry.get("link", ""),
            "title": normalize_text(entry.get("title", "")),
            "summary": normalize_text(entry.get("summary", "")),
            "published": entry.get("published", "") or entry.get("updated", ""),
            "source": source,
        }
        for entry in feed.entries[:30]
    ]
    return entries


def parse_anthropic_page(response):
    soup = BeautifulSoup(response.text, "html.parser")
    entries = []
    for article in soup.select("a[href*='/news/']")[:30]:
        title = normalize_text(article.get_text(" ", strip=True))
        url = normalize_url(urljoin(response.url, article.get("href", "")))
        if title and url:
            card = article.find_parent("article") or article.parent
            summary_element = card.find("p") if card else None
            date_element = card.find("time") if card else None
            summary = (
                normalize_text(summary_element.get_text(" ", strip=True))
                if summary_element
                else ""
            )
            published = ""
            if date_element:
                published = normalize_text(
                    date_element.get("datetime") or date_element.get_text(" ", strip=True)
                )
            entries.append({
                "url": url,
                "title": title,
                "summary": summary,
                "published": published,
                "source": "Anthropic",
            })
    if not entries:
        raise ValueError("Anthropic news page contained no parseable articles")
    return entries


def fetch_source(source, source_type, source_url):
    last_error = None
    for attempt in range(3):
        try:
            response = requests.get(
                source_url,
                timeout=20,
                headers={"User-Agent": "VishesCareerBot/1.0"},
                verify=certifi.where(),
            )
            response.raise_for_status()
            return parse_anthropic_page(response) if source_type == "web" else parse_feed(source, response)
        except requests.RequestException as error:
            last_error = error
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"Unable to fetch after 3 attempts: {last_error}")


def store_news(entries, connection):
    stored = []
    existing = connection.execute("SELECT url, title, summary FROM news").fetchall()
    for entry in entries:
        url = normalize_url(entry["url"])
        title = normalize_text(entry["title"])
        summary = normalize_text(entry["summary"])
        source = entry.get("source", "")
        topic_text = f"{title} {summary}"
        if source.startswith("arXiv"):
            topic_text += f" {source}"
        if not url or not title or not NEWS_TOPIC_PATTERN.search(topic_text):
            continue
        if any(url == row[0] or is_same_story(title, summary, row[1], row[2]) for row in existing):
            continue
        connection.execute(
            """
            INSERT INTO news
            (url, title, source, summary, importance, published_at, created_at, content_hash, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                title,
                entry["source"],
                summary,
                importance_score(title, summary),
                entry["published"],
                datetime.now(timezone.utc).isoformat(),
                content_hash(title, summary),
                topic_category(title, summary),
            ),
        )
        existing.append((url, title, summary))
        stored.append(
            {
                **entry,
                "id": connection.execute("SELECT last_insert_rowid()").fetchone()[0],
                "url": url,
                "title": title,
                "summary": summary,
                "category": topic_category(title, summary),
            }
        )
    return stored


def fetch_news(path=DB_PATH, return_status=False):
    initialize_database(path)
    stored = []
    successful_sources = 0
    issues = []
    connection = sqlite3.connect(path)
    try:
        ensure_news_columns(connection)
        for source, source_type, source_url in NEWS_SOURCES:
            try:
                entries = fetch_source(source, source_type, source_url)
                new_entries = store_news(entries, connection)
                stored.extend(new_entries)
                connection.commit()
                successful_sources += 1
                record_collection_run("news", source, True, items=len(entries), path=path)
                print(
                    f"{source}: collected {len(entries)} entries, "
                    f"{len(new_entries)} new AI/ML articles"
                )
            except (requests.RequestException, RuntimeError, ValueError, sqlite3.Error) as error:
                message = f"{source}: {error}"
                print(f"{message}")
                issues.append(message)
                connection.rollback()
                record_collection_run("news", source, False, error=message, path=path)
        if not successful_sources:
            raise RuntimeError("Failed to fetch AI news from every configured source")
        connection.commit()
    finally:
        connection.close()
    if return_status:
        return stored, successful_sources, issues
    return stored


def send_news_alerts(items, path=DB_PATH):
    connection = sqlite3.connect(path)
    try:
        candidate_ids = [item["id"] for item in items if item.get("id")]
        if not candidate_ids:
            return 0
        placeholders = ",".join("?" for _ in candidate_ids)
        pending = connection.execute(
            f"""
            SELECT id, url, title, source, summary, published_at, category
            FROM news
            WHERE id IN ({placeholders})
              AND importance >= ?
              AND notified_at IS NULL
            ORDER BY importance DESC, created_at DESC
            LIMIT 5
            """,
            (*candidate_ids, IMPORTANT_NEWS_THRESHOLD),
        ).fetchall()
        pending = [row for row in pending if is_recent_publication(row[5])]
        if not pending:
            return 0

        lines = ["🚨 IMPORTANT AI/ML UPDATES"]
        included = []
        for index, row in enumerate(pending, start=1):
            summary = clean_summary(row[4])
            update = (
                f"\n\n{index}. {row[2]}\n{row[3]} · {format_news_date(row[5])}"
                f"\n{summary or 'Publisher did not provide a summary.'}"
                f"\nTopic: {row[6] or 'Breaking AI News'}\n🔗 {row[1]}"
            )
            if sum(map(len, lines)) + len(update) > 3800:
                break
            lines.append(update)
            included.append(row)
        if not included:
            return 0
        send_telegram_message("\n".join(lines))
        connection.execute("BEGIN")
        connection.executemany(
            "UPDATE news SET notified_at = ? WHERE id = ? AND notified_at IS NULL",
            [(datetime.now(timezone.utc).isoformat(), row[0]) for row in included],
        )
        connection.commit()
        return len(included)
    finally:
        connection.close()


def clean_summary(value):
    return normalize_text(BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True))


def format_news_date(value):
    if not value:
        return "Date not provided"
    try:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(str(value))
        return parsed.strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return normalize_text(value)


def is_recent_publication(value, days=14):
    if not value:
        return True
    try:
        try:
            published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            published = parsedate_to_datetime(str(value))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published >= datetime.now(timezone.utc) - timedelta(days=days)
    except (TypeError, ValueError, OverflowError):
        return True


def why_it_matters(category):
    implications = {
        "New Model Release": "Useful for comparing newly announced model capabilities.",
        "Research Breakthrough": "Adds new research evidence or methods to follow.",
        "Agentic AI Developments": "Relevant to teams building or evaluating AI-agent workflows.",
        "LLM and RAG Updates": "Relevant to teams building language-model and retrieval systems.",
        "Open-Source AI Tools": "May change the tools available to build or run AI systems.",
        "Computer Vision and Deep Learning": "Relevant to teams tracking vision and deep-learning methods.",
        "AI Industry and Company Announcements": "Signals a change in the AI industry or company landscape.",
        "Breaking AI News": "A timely development in AI/ML worth monitoring.",
    }
    return implications.get(category, implications["Breaking AI News"])


def send_daily_news_report(path=DB_PATH, report_date=None):
    initialize_database(path)
    report_date = report_date or datetime.now(INDIA_TIMEZONE).date().isoformat()
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute("BEGIN IMMEDIATE")
        already_sent = connection.execute(
            "SELECT 1 FROM daily_reports WHERE report_date = ? AND report_type = 'news'",
            (report_date,),
        ).fetchone()
        if already_sent:
            connection.rollback()
            return {"already_sent": True, "items": 0}

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=36)).isoformat()
        rows = connection.execute(
            """
            SELECT url, title, source, summary, published_at, category
            FROM news
            WHERE created_at >= ? AND digest_sent_at IS NULL
            ORDER BY importance DESC, created_at DESC
            LIMIT 200
            """,
            (cutoff,),
        ).fetchall()
        rows = [row for row in rows if is_recent_publication(row[4])][:10]
        lines = [f"🧠 DAILY AI/ML TRENDING REPORT — {report_date}"]
        included_urls = []
        if rows:
            lines.append(f"Top {len(rows)} recent, source-verified developments:")
            for index, row in enumerate(rows, start=1):
                category = row[5] or "Breaking AI News"
                summary = clean_summary(row[3])
                research_type = (
                    "Research paper"
                    if (row[2] or "").startswith("arXiv")
                    else "Announcement / article"
                )
                story = (
                    f"\n\n{index}. {row[1]}\nPublisher: {row[2] or 'Not specified'}"
                    f" · Published: {format_news_date(row[4])}"
                    f"\nType: {research_type}\nTopic: {category}"
                    f"\nWhat happened: {summary or 'Publisher did not provide a summary.'}"
                    f"\nWhy it matters: {why_it_matters(category)}\n🔗 {row[0]}"
                )
                if sum(map(len, lines)) + len(story) > 3800:
                    break
                lines.append(story)
                included_urls.append(row[0])
        else:
            lines.append("No new AI/ML developments were collected in the reporting window.")

        send_telegram_message("\n".join(lines))
        connection.execute(
            """
            INSERT INTO daily_reports (report_date, report_type, sent_at)
            VALUES (?, 'news', ?)
            """,
            (report_date, datetime.now(timezone.utc).isoformat()),
        )
        if included_urls:
            placeholders = ",".join("?" for _ in included_urls)
            connection.execute(
                f"UPDATE news SET digest_sent_at = ? WHERE url IN ({placeholders})",
                (datetime.now(timezone.utc).isoformat(), *included_urls),
            )
        connection.commit()
        return {"already_sent": False, "items": len(included_urls)}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def run_news_engine(path=DB_PATH, daily_report=False):
    items, sources_checked, issues = fetch_news(path, return_status=True)
    try:
        alerts = send_news_alerts(items, path)
        print(
            f"News engine: {sources_checked} sources succeeded; "
            f"collected {len(items)} new articles; sent {alerts} important update(s)"
        )
    except (requests.RequestException, RuntimeError, sqlite3.Error) as error:
        alerts = 0
        issues.append(f"Important-news notification failed: {error}")
        print(issues[-1])

    report = None
    if daily_report:
        try:
            report = send_daily_news_report(path)
            print(
                "Daily AI/ML report: "
                + ("already sent" if report["already_sent"] else f'sent with {report["items"]} article(s)')
            )
        except (requests.RequestException, RuntimeError, sqlite3.Error, ValueError) as error:
            issues.append(f"Daily AI/ML report failed: {error}")
            print(issues[-1])
    return {
        "new_articles": len(items),
        "sources_checked": sources_checked,
        "important_alerts": alerts,
        "daily_report": report,
        "issues": issues,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-report", action="store_true")
    arguments = parser.parse_args()
    run_news_engine(daily_report=arguments.daily_report)
