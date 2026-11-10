import argparse
import sys

from career_engine import DB_PATH
from jobs import run_global_job_engine
from news_engine import run_news_engine


def run(daily_report=False, path=DB_PATH):
    results = {}
    failures = []

    try:
        results["jobs"] = run_global_job_engine(path)
        print(
            "Job engine complete: "
            f'{results["jobs"]["unique_jobs"]} new listings, '
            f'{results["jobs"]["new_eligible"]} alerts, '
            f'{results["jobs"]["sources_checked"]} sources checked'
        )
        failures.extend(results["jobs"]["issues"])
    except Exception as error:
        message = f"Job engine failed: {error}"
        print(message)
        failures.append(message)

    try:
        results["news"] = run_news_engine(path, daily_report=daily_report)
        failures.extend(results["news"]["issues"])
    except Exception as error:
        message = f"News engine failed: {error}"
        print(message)
        failures.append(message)

    print(
        "Bot run finished: "
        f'{len(failures)} issue(s); '
        f'job alerts={results.get("jobs", {}).get("new_eligible", 0)}, '
        f'new news articles={results.get("news", {}).get("new_articles", 0)}'
    )
    return {"results": results, "issues": failures}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the AI/ML job and news engines.")
    parser.add_argument(
        "--daily-report",
        action="store_true",
        help="Send today's Asia/Kolkata AI/ML news report if it has not already been sent.",
    )
    arguments = parser.parse_args(argv)
    result = run(daily_report=arguments.daily_report)
    return 1 if result["issues"] else 0


if __name__ == "__main__":
    sys.exit(main())
