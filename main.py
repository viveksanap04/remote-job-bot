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


CRITICAL_MARKERS = (
    "engine failed",
    "processing failed",
    "notification failed",
    "report failed",
)


def exit_status(result):
    """Fail the process when an engine is down or an alert could not be delivered.

    A single source outage is recorded and printed, but it does not fail the run
    when another source still produced results.
    """
    results = result["results"]
    if "jobs" not in results or "news" not in results:
        return 1
    for name in ("jobs", "news"):
        engine = results[name]
        if engine.get("sources_checked", 0) == 0 and engine.get("issues"):
            return 1
    for issue in result["issues"]:
        lowered = issue.lower()
        if any(marker in lowered for marker in CRITICAL_MARKERS):
            return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the AI/ML job and news engines.")
    parser.add_argument(
        "--daily-report",
        action="store_true",
        help="Send today's Asia/Kolkata AI/ML news report if it has not already been sent.",
    )
    arguments = parser.parse_args(argv)
    result = run(daily_report=arguments.daily_report)
    return exit_status(result)


if __name__ == "__main__":
    sys.exit(main())
