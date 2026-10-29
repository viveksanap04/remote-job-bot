import unittest

from career_engine import extract_skills
from skill_intelligence import compare_skill_metrics, compute_skill_metrics, deduplicate_jobs


class SkillMetricsTests(unittest.TestCase):
    def test_skill_vocabulary_recognizes_common_aliases(self):
        skills = extract_skills(
            "Python, scikit-learn, sklearn, pandas, LangChain, PySpark, AWS, "
            "LLMs, retrieval-augmented generation"
        )
        self.assertIn("Python", skills)
        self.assertIn("scikit-learn", skills)
        self.assertIn("Pandas", skills)
        self.assertIn("LangChain", skills)
        self.assertIn("Spark", skills)
        self.assertIn("AWS", skills)
        self.assertIn("LLMs", skills)
        self.assertIn("RAG", skills)

    def test_extracts_counts_per_distinct_job_and_skill_combinations(self):
        jobs = [
            {"dedupe_key": "one", "skills": "Python, SQL"},
            {"dedupe_key": "two", "skills": ["Python", "PyTorch"]},
            {"dedupe_key": "one", "skills": ["Python", "SQL"]},
        ]
        self.assertEqual(len(deduplicate_jobs(jobs)), 2)

        metrics = compute_skill_metrics(jobs)
        self.assertEqual(metrics["unique_jobs"], 2)
        self.assertEqual(metrics["skills"]["Python"], 2)
        self.assertEqual(metrics["skills"]["SQL"], 1)
        self.assertEqual(metrics["combinations"]["Python + SQL"], 1)

    def test_trends_require_minimum_sample_and_compare_job_percentages(self):
        self.assertIsNone(
            compare_skill_metrics(
                {"unique_jobs": 4, "skills": {"Python": 4}},
                {"unique_jobs": 5, "skills": {"Python": 2}},
            )
        )
        changes = compare_skill_metrics(
            {"unique_jobs": 5, "skills": {"Python": 4}},
            {"unique_jobs": 5, "skills": {"Python": 2}},
        )
        self.assertEqual(changes["Python"], 40)


if __name__ == "__main__":
    unittest.main()
