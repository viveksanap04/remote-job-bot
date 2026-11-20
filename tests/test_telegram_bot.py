import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from career_engine import initialize_database, save_job
from telegram_bot import (
    deterministic_search_filters,
    dispatch_pending,
    enqueue_message,
    enqueue_job_alerts,
    process_telegram_update,
    register_user,
    search_jobs,
    update_preference,
    update_saved_job,
    verify_webhook_secret,
)


def build_job(title="Graduate AI Engineer", job_id="entry", experience="Fresher / Entry Level"):
    return {
        "title": title,
        "company": "Example AI",
        "source": "Test",
        "link": f"https://example.com/{job_id}",
        "application_link": f"https://example.com/{job_id}/apply",
        "location": "India",
        "remote_status": "fully_remote",
        "india_eligibility": "eligible",
        "employment_category": "India Remote",
        "experience_group": "fresher",
        "experience_level": experience,
        "analysis": {
            "dedupe_key": f"example ai|{job_id}",
            "experience": "0-2 years",
            "location": "India",
            "salary": {"min": None, "max": None, "currency": "", "period": ""},
            "skills": ["Python"],
            "score": 85,
        },
    }


class TelegramChatbotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "career.db")
        initialize_database(self.path)
        self.user_id = register_user(
            {"id": 123, "username": "tester", "first_name": "Test"},
            456,
            self.path,
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_natural_language_search_extracts_structured_job_filters(self):
        filters = deterministic_search_filters(
            "show fresher remote Python jobs in India"
        )
        self.assertEqual(filters["experience_level"], "Fresher / Entry Level")
        self.assertEqual(filters["remote_status"], "fully_remote")
        self.assertEqual(filters["india_eligibility"], "eligible")
        self.assertEqual(filters["skills"], ["Python"])
        self.assertNotIn("keywords", filters)
        self.assertEqual(
            deterministic_search_filters("remote Python jobs not in India")[
                "india_eligibility"
            ],
            "ineligible",
        )

    def test_search_uses_job_filters_and_persisted_user_preferences(self):
        save_job(build_job(), self.path)
        save_job(
            build_job("Senior AI Engineer", "senior", "Senior"),
            self.path,
        )
        jobs = search_jobs(
            self.user_id,
            "show fresher remote Python jobs in India",
            self.path,
        )
        self.assertEqual([job["title"] for job in jobs], ["Graduate AI Engineer"])

        update_preference(self.user_id, "skills", "Python", self.path)
        update_preference(self.user_id, "remote", "fully_remote", self.path)
        saved = search_jobs(self.user_id, "AI jobs", self.path)
        self.assertTrue(saved)
        self.assertTrue(all(job["remote_status"] == "fully_remote" for job in saved))

    @patch.dict(
        "os.environ",
        {
            "LLM_API_URL": "https://llm.example/v1/chat/completions",
            "LLM_API_KEY": "test-key",
            "LLM_MODEL": "test-model",
        },
    )
    @patch("telegram_bot.requests.post")
    def test_llm_fallback_requires_user_opt_in(self, post):
        save_job(build_job(), self.path)
        response = post.return_value
        response.json.return_value = {
            "choices": [{"message": {"content": '{"keywords":"Engineer"}'}}]
        }

        search_jobs(self.user_id, "find roles that fit my background", self.path)
        post.assert_not_called()

        update_preference(self.user_id, "llm", "on", self.path)
        search_jobs(self.user_id, "find roles that fit my background", self.path)
        post.assert_called_once()

    def test_saved_job_actions_are_idempotent_and_user_scoped(self):
        save_job(build_job(), self.path)
        connection = sqlite3.connect(self.path)
        try:
            job_id = connection.execute("SELECT id FROM jobs").fetchone()[0]
        finally:
            connection.close()

        self.assertTrue(update_saved_job(self.user_id, job_id, "Saved", self.path))
        self.assertTrue(update_saved_job(self.user_id, job_id, "Applied", self.path))
        connection = sqlite3.connect(self.path)
        try:
            rows = connection.execute(
                "SELECT status FROM user_saved_jobs WHERE user_id = ? AND job_id = ?",
                (self.user_id, job_id),
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(rows, [("Applied",)])

    @patch("telegram_bot.send_telegram_chat_message", return_value={"ok": True})
    def test_updates_are_idempotent_and_commands_enqueue_replies(self, send_message):
        update = {
            "update_id": 1001,
            "message": {
                "from": {"id": 123, "first_name": "Test"},
                "chat": {"id": 456},
                "text": "/start",
            },
        }
        self.assertTrue(process_telegram_update(update, self.path))
        self.assertFalse(process_telegram_update(update, self.path))
        send_message.assert_called_once()
        self.assertIn("Welcome", send_message.call_args.args[1])

    def test_outbox_retries_failed_delivery_and_marks_success(self):
        enqueue_message(self.user_id, 456, "retry-test", "Hello", path=self.path)
        with patch(
            "telegram_bot.send_telegram_chat_message",
            side_effect=RuntimeError("Telegram unavailable"),
        ):
            self.assertEqual(dispatch_pending(self.path), 0)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT status, attempts FROM notification_outbox WHERE dedupe_key = 'retry-test'"
            ).fetchone()
            connection.execute(
                "UPDATE notification_outbox SET next_attempt_at = '2000-01-01T00:00:00+00:00' "
                "WHERE dedupe_key = 'retry-test'"
            )
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(row, ("pending", 1))

        with patch(
            "telegram_bot.send_telegram_chat_message",
            return_value={"ok": True},
        ):
            self.assertEqual(dispatch_pending(self.path), 1)
        connection = sqlite3.connect(self.path)
        try:
            row = connection.execute(
                "SELECT status, attempts FROM notification_outbox WHERE dedupe_key = 'retry-test'"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row, ("sent", 2))

    @patch.dict("os.environ", {"TELEGRAM_WEBHOOK_SECRET": "expected-secret"})
    def test_webhook_secret_is_required_and_compared_exactly(self):
        self.assertTrue(verify_webhook_secret("expected-secret"))
        self.assertFalse(verify_webhook_secret("wrong-secret"))
        self.assertFalse(verify_webhook_secret(None))

    @patch("telegram_bot.send_telegram_chat_message", return_value={"ok": True})
    def test_new_jobs_queue_personalized_user_alerts(self, send_message):
        job = build_job()
        save_job(job, self.path)
        self.assertEqual(enqueue_job_alerts(job, self.path), 1)
        send_message.assert_called_once()
        self.assertIn("Graduate AI Engineer", send_message.call_args.args[1])
        self.assertIsNotNone(send_message.call_args.args[2])

    @patch("telegram_bot.send_telegram_chat_message", return_value={"ok": True})
    def test_default_personal_alerts_exclude_hybrid_jobs(self, send_message):
        job = build_job("Hybrid AI Engineer", "hybrid")
        job["remote_status"] = "hybrid"
        save_job(job, self.path)
        self.assertEqual(enqueue_job_alerts(job, self.path), 0)
        send_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
