import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from career_engine import (
    has_job_alerted,
    initialize_database,
    mark_job_alerted,
    record_collection_run,
    save_job,
)
from jobs import process_job, run_global_job_engine
from skill_intelligence import (
    EXPECTED_JOB_SOURCES,
    _coverage_is_complete,
    _load_jobs_for_date,
    _latest_source_results,
    _period_metrics,
)


def build_job(source, url):
    return {
        "title": "Junior AI Engineer",
        "company": "Example AI",
        "source": source,
        "link": url,
        "application_link": url,
        "location": "Worldwide",
        "salary": "",
        "remote_status": "fully_remote",
        "india_eligibility": "eligible",
        "employment_category": "India Remote",
        "experience_group": "junior",
        "analysis": {
            "dedupe_key": "example ai|junior ai engineer",
            "location": "Worldwide",
            "experience": "Not specified",
            "salary": {"min": None, "max": None, "currency": "", "period": ""},
            "skills": ["Python", "PyTorch"],
            "score": 75,
        },
    }


def build_alias_job():
    job = build_job("Other board", "https://example.com/job")
    job.update({"title": "AI Engineer", "company": "Alternate company"})
    job["analysis"]["dedupe_key"] = "alternate company|ai engineer"
    return job


class JobDeduplicationTests(unittest.TestCase):
    def test_cross_source_jobs_share_one_database_record_and_daily_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            self.assertTrue(save_job(build_job("Remote OK", "https://example.com/job"), path))
            second_source = build_job("Remotive", "https://example.com/job")
            second_source["analysis"]["skills"] = ["SQL"]
            self.assertFalse(save_job(second_source, path))

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM job_observations").fetchone()[0],
                    1,
                )
                sources = connection.execute("SELECT source FROM jobs").fetchone()[0]
                self.assertEqual(sources, "Remote OK|Remotive")
                skills = connection.execute("SELECT skills FROM jobs").fetchone()[0]
                self.assertEqual(set(skills.split(", ")), {"Python", "PyTorch", "SQL"})
                observation_skills = connection.execute(
                    "SELECT skills FROM job_observations"
                ).fetchone()[0]
                self.assertEqual(set(observation_skills.split(", ")), {"Python", "PyTorch", "SQL"})
            finally:
                connection.close()

            key = "example ai|junior ai engineer"
            self.assertFalse(has_job_alerted(key, path))
            mark_job_alerted(key, path)
            self.assertTrue(has_job_alerted(key, path))

    def test_same_listing_url_with_different_source_metadata_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            save_job(build_job("Remote OK", "https://example.com/job"), path)
            alias = build_alias_job()
            self.assertFalse(save_job(alias, path))
            self.assertEqual(alias["analysis"]["dedupe_key"], "example ai|junior ai engineer")

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
            finally:
                connection.close()

    def test_application_url_deduplicates_distinct_listing_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            first = build_job("Remote OK", "https://example.com/remote-ok")
            first["application_link"] = "https://boards.greenhouse.io/example/job"
            save_job(first, path)

            second = build_job("Remotive", "https://example.com/remotive")
            second["application_link"] = first["application_link"]
            second["analysis"]["dedupe_key"] = "alternate|job title"
            self.assertFalse(save_job(second, path))

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_historical_metrics_use_immutable_observation_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            job = build_job("Remote OK", "https://example.com/job")
            job["experience_group"] = "fresher"
            save_job(job, path)

            connection = sqlite3.connect(path)
            try:
                observed_date = connection.execute(
                    "SELECT observed_date FROM job_observations"
                ).fetchone()[0]
                connection.execute(
                    """
                    UPDATE jobs
                    SET skills = 'SQL', experience_group = 'experienced',
                        remote_status = 'unknown', india_eligibility = 'unknown',
                        employment_category = 'unknown'
                    """
                )
                connection.commit()

                historical_job = _load_jobs_for_date(connection, observed_date)[0]
                self.assertEqual(historical_job["skills"], "Python, PyTorch")
                self.assertEqual(historical_job["experience_group"], "fresher")
                self.assertEqual(historical_job["remote_status"], "fully_remote")
                self.assertEqual(historical_job["india_eligibility"], "eligible")

                source_results = {
                    observed_date: {
                        source: {"success": True, "error": ""}
                        for source in EXPECTED_JOB_SOURCES
                    }
                }
                metrics = _period_metrics(
                    connection,
                    observed_date,
                    [0],
                    "fresher",
                    source_results,
                )
                self.assertEqual(metrics["unique_jobs"], 1)
                self.assertEqual(metrics["skills"]["Python"], 1)
                self.assertNotIn("SQL", metrics["skills"])
            finally:
                connection.close()

    def test_legacy_observations_do_not_qualify_for_trend_comparisons(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            save_job(build_job("Remote OK", "https://example.com/job"), path)
            for source in EXPECTED_JOB_SOURCES:
                record_collection_run("jobs", source, True, path=path)

            connection = sqlite3.connect(path)
            try:
                observed_date = connection.execute(
                    "SELECT observed_date FROM job_observations"
                ).fetchone()[0]
                connection.execute(
                    "UPDATE job_observations SET snapshot_version = 0"
                )
                connection.commit()
                source_results = _latest_source_results(connection, observed_date)
                self.assertFalse(_coverage_is_complete(source_results, observed_date))
            finally:
                connection.close()

    @patch("jobs.append_sent_job")
    @patch("jobs.get_application_link", return_value="https://boards.greenhouse.io/example/job")
    @patch("jobs.send_telegram_message", return_value={"ok": True})
    def test_confirmed_eligible_job_is_sent_and_persisted_once(
        self,
        send_message,
        _application_link,
        _append_sent_job,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            job = {
                **build_job("Remotive", "https://example.com/job"),
                "summary": "Junior role. Python and PyTorch. Remote worldwide.",
                "location": "Worldwide",
                "remote": True,
            }
            self.assertEqual(process_job(job, "Remotive", set(), path), (True, True))
            self.assertEqual(process_job(job, "Remote OK", set(), path), (False, False))
            send_message.assert_called_once()

            connection = sqlite3.connect(path)
            try:
                row = connection.execute(
                    """
                    SELECT remote_status, india_eligibility, experience_group,
                           company_verification, application_verified, notified_at
                    FROM jobs
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[:5], ("fully_remote", "eligible", "junior", "Unverified", 0))
            self.assertIsNotNone(row[5])
            self.assertIn(
                "NEW ELIGIBLE FRESHER/JUNIOR AI/ML JOB",
                send_message.call_args.args[0],
            )

    @patch("jobs.append_sent_job")
    @patch("jobs.get_application_link")
    @patch("jobs.send_telegram_message", return_value={"ok": True})
    def test_alert_requires_fresher_remote_and_explicit_india_eligibility(
        self,
        send_message,
        _application_link,
        _append_sent_job,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            unknown_india_job = {
                **build_job("Remotive", "https://example.com/unknown-india"),
                "title": "Junior AI Engineer",
                "summary": "Junior role. Remote. Python and PyTorch.",
                "location": "Remote",
                "remote": True,
            }
            self.assertEqual(
                process_job(unknown_india_job, "Remotive", set(), path),
                (True, False),
            )

            unknown_experience_job = {
                **build_job("Remotive", "https://example.com/unknown-experience"),
                "title": "AI Engineer",
                "summary": "Remote worldwide. Python and PyTorch.",
                "location": "Worldwide",
                "remote": True,
            }
            self.assertEqual(
                process_job(unknown_experience_job, "Remotive", set(), path),
                (True, False),
            )

            experienced_job = {
                **build_job("Remotive", "https://example.com/experienced"),
                "title": "ML Engineer",
                "summary": "3+ years experience. Remote worldwide. Python and PyTorch.",
                "location": "Worldwide",
                "remote": True,
            }
            self.assertEqual(
                process_job(experienced_job, "Remotive", set(), path),
                (True, False),
            )

            restricted_job = {
                **build_job("Remotive", "https://example.com/us-only"),
                "title": "Junior ML Engineer",
                "summary": "0-2 years experience. Remote role. US only. Python and PyTorch.",
                "location": "Remote, US only",
                "remote": True,
            }
            self.assertEqual(
                process_job(restricted_job, "Remotive", set(), path),
                (True, False),
            )
            send_message.assert_not_called()
            _application_link.assert_not_called()

    @patch("jobs.load_sent_jobs", return_value=set())
    @patch("jobs.fetch_source_jobs", side_effect=[RuntimeError("source unavailable"), []])
    @patch(
        "jobs.SOURCE_SPECS",
        (
            ("Failed source", "fake", "https://example.com/fail"),
            ("Available source", "fake", "https://example.com/ok"),
        ),
    )
    def test_job_source_failure_does_not_stop_other_sources(
        self, _fetch_source, _load_sent_jobs
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            result = run_global_job_engine(path)
            connection = sqlite3.connect(path)
            try:
                statuses = connection.execute(
                    "SELECT source, success FROM collection_runs ORDER BY source"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(result["sources_checked"], 1)
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(statuses, [("Available source", 1), ("Failed source", 0)])

    @patch("jobs.load_sent_jobs", return_value=set())
    @patch(
        "jobs.fetch_source_jobs",
        return_value=[
            {
                "title": "Graduate AI Engineer",
                "company": "Example AI",
                "summary": "Graduate role. Remote worldwide. Python and PyTorch.",
                "link": "https://example.com/graduate-ai",
                "application_link": "",
                "location": "Worldwide",
                "salary": "",
                "remote": True,
            }
        ],
    )
    @patch("jobs.get_application_link", return_value="https://example.com/apply")
    @patch("jobs.send_telegram_message", side_effect=RuntimeError("Telegram unavailable"))
    @patch(
        "jobs.SOURCE_SPECS",
        (("Test source", "fake", "https://example.com/jobs"),),
    )
    def test_job_alert_delivery_failure_is_reported(
        self,
        _send_message,
        _application_link,
        _fetch_source,
        _load_sent_jobs,
    ):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            result = run_global_job_engine(path)
            connection = sqlite3.connect(path)
            try:
                status = connection.execute(
                    "SELECT success, error FROM collection_runs WHERE engine = 'jobs'"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(result["sources_checked"], 1)
        self.assertTrue(any("Telegram unavailable" in issue for issue in result["issues"]))
        self.assertEqual(status[0], 0)
        self.assertIn("Telegram unavailable", status[1])


if __name__ == "__main__":
    unittest.main()
