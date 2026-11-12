import unittest
from unittest.mock import patch

import main


class MainOrchestrationTests(unittest.TestCase):
    @patch("main.run_news_engine", return_value={"new_articles": 3, "issues": []})
    @patch(
        "main.run_global_job_engine",
        side_effect=RuntimeError("job source failure"),
    )
    def test_news_engine_runs_when_job_engine_fails(self, _jobs, news):
        result = main.run(daily_report=True, path="test.db")

        news.assert_called_once_with("test.db", daily_report=True)
        self.assertIn("job source failure", result["issues"][0])
        self.assertEqual(result["results"]["news"]["new_articles"], 3)
        self.assertEqual(main.exit_status(result), 1)

    @patch("main.run_news_engine", side_effect=RuntimeError("news source failure"))
    @patch(
        "main.run_global_job_engine",
        return_value={
            "unique_jobs": 2,
            "new_eligible": 1,
            "sources_checked": 6,
            "issues": [],
        },
    )
    def test_news_failure_does_not_discard_job_results(self, jobs, _news):
        result = main.run(path="test.db")

        jobs.assert_called_once_with("test.db")
        self.assertEqual(result["results"]["jobs"]["new_eligible"], 1)
        self.assertIn("news source failure", result["issues"][0])
        self.assertEqual(main.exit_status(result), 1)

    @patch(
        "main.run_news_engine",
        return_value={"new_articles": 1, "sources_checked": 8, "issues": ["OpenAI: timeout"]},
    )
    @patch(
        "main.run_global_job_engine",
        return_value={
            "unique_jobs": 2,
            "new_eligible": 1,
            "sources_checked": 5,
            "issues": ["Remote OK: temporarily unavailable"],
        },
    )
    def test_partial_source_outage_does_not_fail_the_run(self, _jobs, _news):
        result = main.run(path="test.db")
        self.assertEqual(len(result["issues"]), 2)
        self.assertEqual(main.exit_status(result), 0)

    def test_alert_delivery_failure_fails_the_run(self):
        result = {
            "results": {
                "jobs": {
                    "sources_checked": 4,
                    "issues": ["Remotive job processing failed: Telegram unavailable"],
                },
                "news": {"sources_checked": 3, "issues": []},
            },
            "issues": ["Remotive job processing failed: Telegram unavailable"],
        }
        self.assertEqual(main.exit_status(result), 1)

    def test_total_source_outage_fails_the_run(self):
        result = {
            "results": {
                "jobs": {"sources_checked": 0, "issues": ["every source failed"]},
                "news": {"sources_checked": 2, "issues": []},
            },
            "issues": ["every source failed"],
        }
        self.assertEqual(main.exit_status(result), 1)


if __name__ == "__main__":
    unittest.main()
