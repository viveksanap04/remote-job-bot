import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from career_engine import initialize_database, save_job
from india_jobs import SOURCE_STATUS, run_india_job_engine
from news_engine import (
    ensure_news_columns,
    fetch_news,
    is_recent_publication,
    parse_anthropic_page,
    send_daily_news_report,
    send_news_alerts,
    store_news,
)
from telegram_utils import send_telegram_message


class IndiaNewsTelegramTests(unittest.TestCase):
    def test_india_engine_reports_categories_and_unintegrated_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            result = run_india_job_engine(path)
        self.assertEqual(
            result["categories"],
            {"India Remote": 0, "India Hybrid": 0, "India Onsite": 0},
        )
        self.assertEqual(result["integrated_sources"], [])
        self.assertEqual(set(result["source_limitations"]), set(SOURCE_STATUS))

    def test_india_engine_counts_categories_from_saved_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            for category in ("India Remote", "India Hybrid", "India Onsite"):
                job = {
                    "title": f"Junior AI Engineer {category}",
                    "company": f"Example {category}",
                    "source": "Test",
                    "link": f"https://example.com/{category.replace(' ', '-')}",
                    "application_link": "",
                    "remote_status": "fully_remote" if category == "India Remote" else category.split()[1].lower(),
                    "india_eligibility": "eligible",
                    "employment_category": category,
                    "experience_group": "junior",
                    "analysis": {
                        "dedupe_key": f"example {category}|junior ai engineer",
                        "location": "India",
                        "experience": "junior",
                        "salary": {"currency": ""},
                        "skills": ["Python"],
                        "score": 50,
                    },
                }
                save_job(job, path)
            result = run_india_job_engine(path)
        self.assertEqual(
            result["categories"],
            {"India Remote": 1, "India Hybrid": 1, "India Onsite": 1},
        )

    def test_news_storage_deduplicates_and_assigns_topic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            connection = sqlite3.connect(path)
            try:
                ensure_news_columns(connection)
                item = {
                    "url": "https://example.com/ai-launch",
                    "title": "New AI model launch",
                    "summary": "A research model release.",
                    "published": datetime.now(timezone.utc).date().isoformat(),
                    "source": "Example AI",
                }
                unrelated_item = {
                    "url": "https://example.com/company-update",
                    "title": "Company office expansion",
                    "summary": "A general facilities announcement.",
                    "published": datetime.now(timezone.utc).date().isoformat(),
                    "source": "OpenAI",
                }
                self.assertEqual(len(store_news([item, unrelated_item], connection)), 1)
                self.assertEqual(len(store_news([item], connection)), 0)
                category = connection.execute(
                    "SELECT category FROM news WHERE url = ?",
                    (item["url"],),
                ).fetchone()[0]
                self.assertEqual(category, "New Model Release")
            finally:
                connection.close()

    def test_anthropic_parser_extracts_available_summary_and_publication_date(self):
        response = Mock(
            url="https://www.anthropic.com/news",
            text=(
                '<article><a href="/news/model-release">Model release</a>'
                "<p>A short announcement about the model.</p>"
                '<time datetime="2026-11-03">Nov 3, 2026</time></article>'
            ),
        )

        items = parse_anthropic_page(response)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["summary"], "A short announcement about the model.")
        self.assertEqual(items[0]["published"], "2026-11-03")
        self.assertEqual(items[0]["url"], "https://www.anthropic.com/news/model-release")

    @patch(
        "news_engine.NEWS_SOURCES",
        (
            ("Unavailable source", "rss", "https://example.com/fail"),
            ("Working source", "rss", "https://example.com/ok"),
        ),
    )
    @patch(
        "news_engine.fetch_source",
        side_effect=[
            RuntimeError("feed unavailable"),
            [
                {
                    "url": "https://example.com/ai-research",
                    "title": "AI research release",
                    "summary": "New machine learning research.",
                    "published": datetime.now(timezone.utc).date().isoformat(),
                    "source": "Working source",
                }
            ],
        ],
    )
    def test_news_source_failure_does_not_stop_other_sources(self, _fetch_source):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            items = fetch_news(path)
            connection = sqlite3.connect(path)
            try:
                statuses = connection.execute(
                    "SELECT source, success FROM collection_runs WHERE engine = 'news' ORDER BY source"
                ).fetchall()
            finally:
                connection.close()
        self.assertEqual(len(items), 1)
        self.assertEqual(statuses, [("Unavailable source", 0), ("Working source", 1)])

    def test_daily_news_report_is_sent_at_most_once_per_local_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            connection = sqlite3.connect(path)
            try:
                ensure_news_columns(connection)
                store_news(
                    [
                        {
                            "url": "https://example.com/ai-research",
                            "title": "AI research breakthrough",
                            "summary": "New machine learning research reports a method.",
                            "published": datetime.now(timezone.utc).date().isoformat(),
                            "source": "OpenAI",
                        }
                    ],
                    connection,
                )
                connection.commit()
            finally:
                connection.close()
            messages = Mock(return_value={"ok": True})
            with patch("news_engine.send_telegram_message", messages):
                first = send_daily_news_report(path, report_date="2026-10-29")
                second = send_daily_news_report(path, report_date="2026-10-29")
                next_day = send_daily_news_report(path, report_date="2026-10-30")
        self.assertFalse(first["already_sent"])
        self.assertTrue(second["already_sent"])
        self.assertEqual(messages.call_count, 2)
        report = messages.call_args_list[0].args[0]
        self.assertIn("DAILY AI/ML TRENDING REPORT", report)
        self.assertIn("Publisher: OpenAI", report)
        self.assertIn(
            "Published: " + datetime.now(timezone.utc).date().isoformat(),
            report,
        )
        self.assertIn("Why it matters:", report)
        self.assertIn("https://example.com/ai-research", report)
        self.assertEqual(next_day["items"], 0)
        self.assertNotIn(
            "https://example.com/ai-research",
            messages.call_args_list[1].args[0],
        )

    def test_news_recency_uses_publisher_date_when_available(self):
        recent = (datetime.now(timezone.utc) - timedelta(days=12)).date().isoformat()
        self.assertTrue(is_recent_publication(recent))
        self.assertFalse(is_recent_publication("2020-01-01"))
        self.assertTrue(is_recent_publication(""))

    def test_database_migration_removes_only_skill_report_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "CREATE TABLE daily_skill_metrics (report_date TEXT, skill TEXT)"
                )
                connection.execute(
                    "CREATE TABLE daily_skill_combinations (report_date TEXT, pair TEXT)"
                )
                connection.execute(
                    "ALTER TABLE job_observations ADD COLUMN snapshot_version INTEGER NOT NULL DEFAULT 0"
                )
                connection.execute(
                    """
                    INSERT INTO jobs (dedupe_key, title, listing_url, created_at)
                    VALUES ('job-key', 'AI Engineer', 'https://example.com/job', 'today')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO news (url, title, created_at)
                    VALUES ('https://example.com/news', 'AI research', 'today')
                    """
                )
                connection.commit()
            finally:
                connection.close()

            initialize_database(path)
            connection = sqlite3.connect(path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                self.assertNotIn("daily_skill_metrics", tables)
                self.assertNotIn("daily_skill_combinations", tables)
                observation_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(job_observations)")
                }
                self.assertNotIn("snapshot_version", observation_columns)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM news").fetchone()[0], 1)
            finally:
                connection.close()

    @patch("news_engine.send_telegram_message", return_value={"ok": True})
    def test_important_news_is_not_notified_twice(self, send_message):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            connection = sqlite3.connect(path)
            try:
                ensure_news_columns(connection)
                item = {
                    "url": "https://example.com/model-launch",
                    "title": "New AI model launch and release",
                    "summary": "Research details on a new AI model release.",
                    "published": datetime.now(timezone.utc).date().isoformat(),
                    "source": "OpenAI",
                }
                stored = store_news([item], connection)
                connection.commit()
            finally:
                connection.close()
            self.assertEqual(send_news_alerts(stored, path), 1)
            self.assertEqual(send_news_alerts(stored, path), 0)
        send_message.assert_called_once()

    @patch.dict(os.environ, {"BOT_TOKEN": "test-token", "CHAT_ID": "test-chat"})
    @patch("telegram_utils.requests.post")
    def test_shared_telegram_delivery_uses_successful_response(self, post):
        response = Mock()
        response.json.return_value = {"ok": True}
        post.return_value = response
        result = send_telegram_message("test message")
        self.assertTrue(result["ok"])
        post.assert_called_once()

    def test_engines_persist_data_and_send_separate_telegram_messages(self):
        from jobs import run_global_job_engine
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            job = {
                "title": "Graduate AI Engineer",
                "company": "Example AI",
                "summary": "Remote worldwide role. Python and PyTorch.",
                "link": "https://example.com/graduate-ai",
                "location": "Worldwide",
                "remote": True,
            }
            news_item = {
                "url": "https://example.com/ai-launch",
                "title": "New AI model launch",
                "summary": "An AI model release.",
                "published": datetime.now(timezone.utc).date().isoformat(),
                "source": "OpenAI",
            }
            job_messages = Mock(return_value={"ok": True})
            news_messages = Mock(return_value={"ok": True})
            with (
                patch(
                    "jobs.SOURCE_SPECS",
                    (("Remotive", "remotive", "https://example.com/jobs"),),
                ),
                patch("jobs.load_sent_jobs", return_value=set()),
                patch("jobs.fetch_source_jobs", return_value=[job]),
                patch(
                    "jobs.get_application_link",
                    return_value="https://boards.greenhouse.io/example/job",
                ),
                patch("jobs.send_telegram_message", job_messages),
                patch("jobs.append_sent_job"),
                patch(
                    "news_engine.NEWS_SOURCES",
                    (("OpenAI", "rss", "https://example.com/news"),),
                ),
                patch("news_engine.fetch_source", return_value=[news_item]                ),
                patch("news_engine.send_telegram_message", news_messages),
            ):
                job_result = run_global_job_engine(path)
                news_items = fetch_news(path)
                self.assertEqual(send_news_alerts(news_items, path), 1)
                report_result = send_daily_news_report(path, report_date="2026-10-29")

            self.assertEqual(job_result["new_eligible"], 1)
            self.assertIn(
                "NEW REMOTE AI/ML JOB",
                job_messages.call_args.args[0],
            )
            self.assertIn(
                "IMPORTANT AI/ML UPDATES",
                news_messages.call_args_list[0].args[0],
            )
            self.assertIn(
                "DAILY AI/ML TRENDING REPORT",
                news_messages.call_args_list[1].args[0],
            )
            self.assertEqual(report_result["items"], 1)
            self.assertEqual(
                (job_messages.call_count, news_messages.call_count),
                (1, 2),
            )

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM news").fetchone()[0], 1)
                self.assertIsNotNone(
                    connection.execute("SELECT digest_sent_at FROM news").fetchone()[0]
                )
                self.assertEqual(
                    connection.execute("SELECT report_type FROM daily_reports").fetchone()[0],
                    "news",
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
