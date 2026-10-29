import sqlite3

from career_engine import DB_PATH, initialize_database


SOURCE_STATUS = {
    "Cutshort": "Not integrated: no documented public job API/feed verified; homepage access alone is not a reliable listing integration.",
    "Naukri": "Not integrated: public request returned HTTP 403; no documented public API/feed verified.",
    "Wellfound": "Not integrated: jobs page is publicly reachable, but no documented public listing API/feed verified.",
    "National Career Service": "Not integrated: public portal is reachable, but no documented public job API/feed verified.",
    "Official company career pages": "Not integrated as a global crawl: there is no configured company allowlist or documented aggregate feed.",
}


def run_india_job_engine(path=DB_PATH):
    """Summarize India job categories already collected by the global sources."""
    initialize_database(path)
    connection = sqlite3.connect(path)
    try:
        counts = {
            category: count
            for category, count in connection.execute(
                """
                SELECT employment_category, COUNT(DISTINCT dedupe_key)
                FROM jobs
                WHERE employment_category IN ('India Remote', 'India Hybrid', 'India Onsite')
                GROUP BY employment_category
                """
            )
        }
    finally:
        connection.close()

    return {
        "categories": {
            category: counts.get(category, 0)
            for category in ("India Remote", "India Hybrid", "India Onsite")
        },
        "integrated_sources": [],
        "source_limitations": dict(SOURCE_STATUS),
    }


if __name__ == "__main__":
    result = run_india_job_engine()
    print("India job categories:", result["categories"])
    print("No unsupported India source was scraped or represented as integrated.")
