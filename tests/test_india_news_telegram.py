import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from career_engine import initialize_database, record_collection_run, save_job
from india_jobs import SOURCE_STATUS, run_india_job_engine
from news_engine import ensure_news_columns, fetch_news, store_news
from skill_intelligence import generate_daily_report
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
                    "published": "2026-10-29",
                    "source": "Example AI",
                }
                self.assertEqual(len(store_news([item], connection)), 1)
                self.assertEqual(len(store_news([item], connection)), 0)
                category = connection.execute(
                    "SELECT category FROM news WHERE url = ?",
                    (item["url"],),
                ).fetchone()[0]
                self.assertEqual(category, "Models and releases")
            finally:
                connection.close()

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
                    "published": "2026-10-29",
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

    def test_skill_report_suppresses_zero_result_when_sources_have_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            result = generate_daily_report(path=path, report_date="2026-10-29", send=False)
        self.assertNotIn("message", result)
        self.assertEqual(result["sources_checked"], 0)

    def test_skill_report_labels_partial_source_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            record_collection_run("jobs", "Remote OK", True, items=0, path=path)
            result = generate_daily_report(path=path, report_date="2026-10-29", send=False)
        self.assertIn("1/6 configured global job sources succeeded", result["message"])
        self.assertIn("Collection issues:", result["message"])

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
        from news_engine import send_news_alerts

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
                "published": "2026-10-29",
                "source": "OpenAI",
            }
            job_messages = Mock(return_value={"ok": True})
            news_messages = Mock(return_value={"ok": True})
            skill_messages = Mock(return_value={"ok": True})
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
                patch("news_engine.fetch_source", return_value=[news_item]),
                patch("news_engine.send_telegram_message", news_messages),
                patch("skill_intelligence.send_telegram_message", skill_messages),
            ):
                job_result = run_global_job_engine(path)
                news_items = fetch_news(path)
                self.assertEqual(send_news_alerts(news_items, path), 1)
                skill_result = generate_daily_report(path=path, send=True)

            self.assertEqual(job_result["new_eligible"], 1)
            self.assertIn("NEW FRESHER AI/ML JOB", job_messages.call_args.args[0])
            self.assertIn("DAILY AI / ML NEWS", news_messages.call_args.args[0])
            self.assertIn("DAILY AI/ML SKILL INTELLIGENCE", skill_messages.call_args.args[0])
            self.assertIn("message", skill_result)
            self.assertEqual(
                (job_messages.call_count, news_messages.call_count, skill_messages.call_count),
                (1, 1, 1),
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
                    "skills",
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
