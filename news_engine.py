import hashlib
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
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
    ("MIT Technology Review AI", "rss", "https://www.technologyreview.com/topic/artificial-intelligence/feed/"),
    ("arXiv CS.AI", "rss", "https://export.arxiv.org/rss/cs.AI"),
    ("arXiv ML", "rss", "https://export.arxiv.org/rss/cs.LG"),
    ("arXiv Computer Vision", "rss", "https://export.arxiv.org/rss/cs.CV"),
    ("arXiv Statistical ML", "rss", "https://export.arxiv.org/rss/stat.ML"),
)

IMPORTANT_TERMS = (
    "launch", "release", "model", "funding", "research", "open source",
    "acquisition", "breakthrough", "safety", "agent",
)
NEWS_TOPIC_PATTERN = re.compile(
    r"\b(?:ai|ml|llm|agentic|agents?|genai|transformer|multimodal)\b"
    r"|artificial intelligence|machine learning|deep learning|large language model"
    r"|computer vision|vision-language|neural network|generative ai|robotics",
    re.IGNORECASE,
)
STOP_WORDS = {"about", "after", "and", "from", "into", "that", "the", "this", "with", "your"}


def importance_score(title, summary):
    text = f"{title} {summary}".lower()
    return min(100, 20 + sum(8 for term in IMPORTANT_TERMS if term in text))


def topic_category(title, summary):
    text = f"{title} {summary}".lower()
    categories = (
        ("Models and releases", ("model", "release", "launch")),
        ("Research", ("research", "paper", "study", "arxiv")),
        ("AI safety and policy", ("safety", "policy", "alignment", "governance")),
        ("Developer tools and infrastructure", ("developer", "tool", "infrastructure", "open source")),
        ("Agents and applications", ("agent", "application", "product")),
    )
    return next(
        (category for category, terms in categories if any(term in text for term in terms)),
        "AI industry",
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
            entries.append({
                "url": url,
                "title": title,
                "summary": title,
                "published": "",
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
        curated_ai_source = source in {"OpenAI", "Google DeepMind", "Anthropic", "Hugging Face"}
        if (
            not url
            or not title
            or not (
                curated_ai_source
                or NEWS_TOPIC_PATTERN.search(f"{title} {summary}")
                or (
                    source.startswith("arXiv")
                    and NEWS_TOPIC_PATTERN.search(f"{title} {summary} {source}")
                )
            )
        ):
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
        stored.append({**entry, "url": url, "title": title, "summary": summary})
    return stored


def fetch_news(path=DB_PATH):
    initialize_database(path)
    stored = []
    successful_sources = 0
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
            except (requests.RequestException, RuntimeError, ValueError, sqlite3.Error) as error:
                message = f"{source}: {error}"
                print(f"{message}")
                connection.rollback()
                record_collection_run("news", source, False, error=message, path=path)
        if not successful_sources:
            raise RuntimeError("Failed to fetch AI news from every configured source")
        connection.commit()
    finally:
        connection.close()
    return stored


def send_news_alerts(items, path=DB_PATH):
    connection = sqlite3.connect(path)
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=36)).isoformat()
        pending = connection.execute(
            """
            SELECT id, url, title, source, summary, published_at, category
            FROM news
            WHERE digest_sent_at IS NULL AND created_at >= ?
            ORDER BY importance DESC, published_at DESC
            LIMIT 8
            """,
            (cutoff,),
        ).fetchall()
        digest_items = [
            {
                "id": row[0],
                "url": row[1],
                "title": row[2],
                "source": row[3],
                "summary": row[4] or "",
                "published": row[5] or "",
                "category": row[6] or "AI industry",
            }
            for row in pending
        ]

        lines = [
            f"🧠 DAILY AI / ML NEWS — "
            f"{datetime.now(INDIA_TIMEZONE).strftime('%Y-%m-%d')}"
        ]
        included_ids = []
        if digest_items:
            for index, item in enumerate(digest_items, start=1):
                published = normalize_text(item["published"]) or "Date not provided"
                summary = normalize_text(BeautifulSoup(item["summary"], "html.parser").get_text(" ", strip=True))
                if len(summary) > 220:
                    summary = summary[:217].rsplit(" ", 1)[0] + "..."
                story = (
                    f"\n\n{index}. {item['title']}\n"
                    f"{item['source']} • {published}\n"
                    f"Topic: {item['category']}\n"
                    f"{summary}\n"
                    f"🔗 {item['url']}"
                )
                if sum(map(len, lines)) + len(story) > 3800:
                    break
                lines.append(story)
                included_ids.append(item["id"])
        else:
            return 0

        send_telegram_message("".join(lines))

        if included_ids:
            placeholders = ",".join("?" for _ in included_ids)
            connection.execute(
                f"UPDATE news SET digest_sent_at = ? WHERE id IN ({placeholders})",
                (datetime.now(timezone.utc).isoformat(), *included_ids),
            )
            connection.commit()
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    new_items = fetch_news()
    print(f"Stored {len(new_items)} new AI news items")
    print(f"Sent {send_news_alerts(new_items)} daily AI news digest")
