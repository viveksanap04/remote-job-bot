import unittest

from career_engine import (
    india_eligibility_status,
    is_fresher_experience,
    is_fully_remote,
)


class JobFilterTests(unittest.TestCase):
    def test_only_confirmed_entry_level_experience_is_eligible(self):
        self.assertTrue(is_fresher_experience("Graduate Software Engineer (AI)"))
        self.assertTrue(is_fresher_experience("Junior ML Engineer"))
        self.assertTrue(is_fresher_experience("AI Engineer", "0-2 years experience"))
        self.assertFalse(is_fresher_experience("AI Engineer", "Experience not specified"))
        self.assertFalse(is_fresher_experience("AI Engineer", "3+ years experience"))
        self.assertFalse(
            is_fresher_experience("Junior AI Engineer", "More than 2 years required")
        )
        self.assertFalse(
            is_fresher_experience("Junior AI Engineer", "Three years required")
        )
        self.assertTrue(
            is_fresher_experience("Junior AI Engineer", "Joined three years ago")
        )

    def test_requires_fully_remote_status(self):
        self.assertTrue(is_fully_remote("AI Engineer", remote=True))
        self.assertFalse(is_fully_remote("AI Engineer"))
        self.assertFalse(is_fully_remote("Remote AI Engineer", "Hybrid schedule"))

    def test_india_eligibility_is_tristate(self):
        self.assertEqual(india_eligibility_status(location="Worldwide"), "eligible")
        self.assertEqual(india_eligibility_status("You can work from anywhere"), "eligible")
        self.assertEqual(india_eligibility_status(location="US only"), "ineligible")
        self.assertEqual(
            india_eligibility_status(location="Remote", location_restrictions="US"),
            "ineligible",
        )
        self.assertEqual(india_eligibility_status("Remote, US only"), "ineligible")
        self.assertEqual(india_eligibility_status(), "unknown")
        self.assertEqual(
            india_eligibility_status("Applicants are not eligible in India"),
            "ineligible",
        )


if __name__ == "__main__":
    unittest.main()
