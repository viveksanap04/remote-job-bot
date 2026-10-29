import unittest

from career_engine import (
    detect_experience,
    india_eligibility_status,
    is_fresher_experience,
    is_fully_remote,
    is_india_eligible,
    score_job,
)


class JobEligibilityTests(unittest.TestCase):
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

    def test_requires_explicit_india_eligibility(self):
        self.assertTrue(is_india_eligible(location="India"))
        self.assertTrue(is_india_eligible(location_restrictions=["US", "India"]))
        self.assertTrue(is_india_eligible("We accept applicants from India"))
        self.assertTrue(is_india_eligible("Candidates must be based in India"))
        self.assertFalse(is_india_eligible("Our team has an office in India"))
        self.assertTrue(is_india_eligible(location="Worldwide"))
        self.assertEqual(india_eligibility_status(), "unknown")
        self.assertEqual(india_eligibility_status(location="US only"), "ineligible")
        self.assertFalse(is_india_eligible("Applicants are not eligible in India"))

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
