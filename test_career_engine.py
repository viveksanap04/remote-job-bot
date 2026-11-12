import unittest

import sqlite3
import tempfile
from pathlib import Path

from career_engine import (
    analyze_experience,
    create_application,
    detect_experience,
    detect_location,
    india_eligibility_status,
    initialize_database,
    is_fresher_experience,
    is_fully_remote,
    is_india_eligible,
    score_job,
)


class JobEligibilityTests(unittest.TestCase):
    def test_experience_analysis_classifies_levels_and_keeps_unknown(self):
        self.assertEqual(
            analyze_experience("Graduate AI Engineer")["level"],
            "Fresher / Entry Level",
        )
        self.assertEqual(
            analyze_experience("ML Engineer", "0-2 years experience")["level"],
            "0–2 Years",
        )
        self.assertEqual(
            analyze_experience("ML Engineer", "2-3 years experience")["level"],
            "2–3 Years",
        )
        self.assertEqual(
            analyze_experience("ML Engineer", "3-5 years experience")["level"],
            "3–5 Years",
        )
        self.assertEqual(
            analyze_experience("Senior ML Engineer")["level"],
            "Senior",
        )
        self.assertEqual(
            analyze_experience("ML internship")["level"],
            "Internship",
        )
        self.assertEqual(
            analyze_experience("AI Engineer", "Experience not specified")["level"],
            "Experience not specified",
        )
        self.assertEqual(
            analyze_experience("ML Engineer", "2+ years of experience")["level"],
            "2–3 Years",
        )
        self.assertEqual(
            analyze_experience("ML Engineer", "1-3 years of experience")["level"],
            "2–3 Years",
        )

    def test_experience_analysis_distinguishes_preferred_and_conflicting_ranges(self):
        preferred = analyze_experience(
            "AI Engineer",
            "0-2 years required. 3-5 years preferred.",
        )
        self.assertEqual(preferred["level"], "0–2 Years")
        self.assertEqual(preferred["requirement"], "required")
        self.assertFalse(preferred["conflict"])

        conflict = analyze_experience(
            "AI Engineer",
            "0-2 years required. 5 years experience required.",
        )
        self.assertTrue(conflict["conflict"])

    def test_accepts_fresher_and_two_year_requirements(self):
        self.assertTrue(is_fresher_experience("Graduate AI Engineer"))
        self.assertTrue(is_fresher_experience("ML Engineer", "0-2 years of experience"))
        self.assertTrue(is_fresher_experience("AI Engineer", "2 years experience required"))
        self.assertTrue(is_fresher_experience("AI Engineer", "Up to 2 years of experience"))
        self.assertTrue(is_fresher_experience("Junior ML Engineer"))
        self.assertEqual(detect_experience("Up to 2 years of experience"), "0-2 years")
        self.assertEqual(detect_experience("2 years experience required"), "2 years")

    def test_rejects_unknown_or_over_two_year_requirements(self):
        self.assertFalse(is_fresher_experience("AI Engineer", "Experience not specified"))
        self.assertFalse(is_fresher_experience("AI Engineer", "3+ years of experience"))
        self.assertFalse(is_fresher_experience("AI Engineer", "3-5 years of experience"))
        self.assertFalse(is_fresher_experience("Fresher AI Engineer", "5 years experience required"))
        self.assertFalse(is_fresher_experience("Not an entry-level role"))
        self.assertFalse(is_fresher_experience("AI Engineer", "A graduate degree is required"))

    def test_requires_remote_status_and_rejects_hybrid_roles(self):
        self.assertTrue(is_fully_remote("Remote AI Engineer"))
        self.assertTrue(is_fully_remote("AI Engineer", remote=True))
        self.assertFalse(is_fully_remote("AI Engineer"))
        self.assertFalse(is_fully_remote("Remote AI Engineer", "Hybrid work arrangement"))
        self.assertFalse(is_fully_remote("Remote AI Engineer", "Remote is optional"))
        self.assertFalse(is_fully_remote("Remote AI Engineer", "This is not fully remote"))
        self.assertFalse(is_fully_remote("Remote AI Engineer", remote=False))

    def test_worldwide_remote_does_not_imply_india_eligibility(self):
        self.assertTrue(is_india_eligible(location="India"))
        self.assertTrue(is_india_eligible(location_restrictions=["US", "India"]))
        self.assertTrue(is_india_eligible("We accept applicants from India"))
        self.assertTrue(is_india_eligible("Candidates must be based in India"))
        self.assertFalse(is_india_eligible("Our team has an office in India"))
        self.assertFalse(is_india_eligible(location="Worldwide"))
        self.assertFalse(is_india_eligible("You can work from anywhere"))
        self.assertEqual(india_eligibility_status(location="Worldwide"), "unknown")
        self.assertEqual(india_eligibility_status(), "unknown")
        self.assertEqual(india_eligibility_status(location="US only"), "ineligible")
        self.assertFalse(is_india_eligible("Applicants are not eligible in India"))
        self.assertFalse(is_india_eligible(location="Indiana"))
        self.assertEqual(detect_location("Indiana, USA"), "US")
        self.assertEqual(detect_location("Bengaluru, India"), "India")

    def test_application_tracking_keeps_one_row_per_job(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "career.db")
            initialize_database(path)
            first = create_application(7, path)
            second = create_application(7, path)
            connection = sqlite3.connect(path)
            try:
                count = connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            finally:
                connection.close()
        self.assertEqual(first, second)
        self.assertEqual(count, 1)

    def test_match_score_uses_skills_role_experience_and_india_eligibility(self):
        eligible_score = score_job(
            "AI Engineer",
            "Python and PyTorch. Entry-level role.",
            india_eligible=True,
        )["score"]
        without_india_eligibility = score_job(
            "AI Engineer",
            "Python and PyTorch. Entry-level role.",
            india_eligible=False,
        )["score"]

        self.assertEqual(eligible_score - without_india_eligibility, 15)
        self.assertEqual(
            score_job("Retail Assistant", "Python")["score"],
            8,
        )


if __name__ == "__main__":
    unittest.main()
