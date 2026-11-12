import unittest
from unittest.mock import Mock

from jobs import parse_greenhouse


class GreenhouseSourceTests(unittest.TestCase):
    def test_parses_public_job_board_fields_and_html_content(self):
        response = Mock()
        response.json.return_value = {
            "jobs": [
                {
                    "title": "Remote AI Engineer",
                    "content": "&lt;p&gt;Build machine learning systems.&lt;/p&gt;",
                    "absolute_url": "https://boards.greenhouse.io/example/jobs/123",
                    "company_name": "Example AI",
                    "location": {"name": "Remote - Canada"},
                    "first_published": "2026-11-12T10:00:00Z",
                    "application_deadline": "2026-12-01",
                },
                {"title": "Incomplete listing"},
                None,
            ]
        }

        jobs = parse_greenhouse(response, "Example AI")

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Remote AI Engineer")
        self.assertEqual(jobs[0]["summary"], "Build machine learning systems.")
        self.assertEqual(jobs[0]["company"], "Example AI")
        self.assertEqual(jobs[0]["location"], "Remote - Canada")
        self.assertEqual(jobs[0]["link"], "https://boards.greenhouse.io/example/jobs/123")
        self.assertEqual(jobs[0]["published"], "2026-11-12T10:00:00Z")
        self.assertEqual(jobs[0]["closing"], "2026-12-01")

    def test_rejects_unexpected_greenhouse_response_shape(self):
        response = Mock()
        response.json.return_value = {"positions": []}

        with self.assertRaisesRegex(ValueError, "unexpected Greenhouse response"):
            parse_greenhouse(response, "Example AI")


if __name__ == "__main__":
    unittest.main()
