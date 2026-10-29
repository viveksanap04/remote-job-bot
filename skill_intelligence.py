import itertools
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from career_engine import DB_PATH, INDIA_TIMEZONE, initialize_database
from india_jobs import SOURCE_STATUS as INDIA_SOURCE_STATUS
from jobs import SOURCE_LIMITATIONS, SOURCE_SPECS
from telegram_utils import send_telegram_message


LOCAL_TIMEZONE = INDIA_TIMEZONE
EXPECTED_JOB_SOURCES = {source for source, _, _ in SOURCE_SPECS}
MIN_JOBS_FOR_TREND = 5


def _job_key(job):
    return (
        job.get("dedupe_key")
        or job.get("url")
        or job.get("listing_url")
        or "|".join(
            (
                str(job.get("company", "")).strip().lower(),
                str(job.get("title", "")).strip().lower(),
            )
        )
    )


def deduplicate_jobs(jobs):
    unique = {}
    for job in jobs:
        key = _job_key(job)
        if key.strip("|"):
            unique.setdefault(key, job)
    return list(unique.values())


def compute_skill_metrics(jobs):
    unique_jobs = deduplicate_jobs(jobs)
    skill_counts = Counter()
    pair_counts = Counter()
    for job in unique_jobs:
        raw_skills = job.get("skills", [])
        if isinstance(raw_skills, str):
            skills = {skill.strip() for skill in raw_skills.split(",") if skill.strip()}
        else:
            skills = {str(skill).strip() for skill in raw_skills if str(skill).strip()}
        skill_counts.update(skills)
        pair_counts.update(itertools.combinations(sorted(skills), 2))
    return {
        "unique_jobs": len(unique_jobs),
        "skills": dict(skill_counts),
        "combinations": {
            f"{first} + {second}": count
            for (first, second), count in pair_counts.most_common()
        },
    }


def compare_skill_metrics(current, previous, minimum_jobs=MIN_JOBS_FOR_TREND):
    if (
        current["unique_jobs"] < minimum_jobs
        or previous["unique_jobs"] < minimum_jobs
    ):
        return None

    skill_names = set(current["skills"]) | set(previous["skills"])
    changes = {}
    for skill in skill_names:
        current_rate = current["skills"].get(skill, 0) / current["unique_jobs"]
        previous_rate = previous["skills"].get(skill, 0) / previous["unique_jobs"]
        change = (current_rate - previous_rate) * 100
        if change:
            changes[skill] = change
    return changes


def _local_date(timestamp):
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE).date().isoformat()


def _latest_source_results(connection, start_date):
    rows = connection.execute(
        """
        SELECT source, success, error, completed_at
        FROM collection_runs
        WHERE engine = 'jobs'
        ORDER BY completed_at DESC
        LIMIT 20000
        """
    ).fetchall()
    results = {}
    for source, success, error, completed_at in rows:
        run_date = _local_date(completed_at)
        if run_date < start_date:
            continue
        results.setdefault(run_date, {})
        results[run_date].setdefault(
            source,
            {"success": bool(success), "error": error or ""},
        )
    observation_versions = connection.execute(
        """
        SELECT observed_date, MIN(snapshot_version)
        FROM job_observations
        GROUP BY observed_date
        """
    ).fetchall()
    for observed_date, version in observation_versions:
        if observed_date >= start_date:
            results.setdefault(observed_date, {})["__snapshot_complete__"] = version >= 1
    return results


def _coverage_is_complete(results, day):
    sources = results.get(day, {})
    source_statuses = {
        name: status
        for name, status in sources.items()
        if not name.startswith("__")
    }
    return (
        sources.get("__snapshot_complete__", True)
        and set(source_statuses) == EXPECTED_JOB_SOURCES
        and all(status["success"] for status in source_statuses.values())
    )


def _load_jobs_for_date(connection, report_date):
    rows = connection.execute(
        """
        SELECT j.dedupe_key, j.title, j.company, j.source, o.skills,
               o.experience_group, o.remote_status, o.india_eligibility,
               o.employment_category, o.is_new
        FROM job_observations o
        JOIN jobs j ON j.id = o.job_id
        WHERE o.observed_date = ?
        ORDER BY j.dedupe_key
        """,
        (report_date,),
    ).fetchall()
    columns = (
        "dedupe_key",
        "title",
        "company",
        "source",
        "skills",
        "experience_group",
        "remote_status",
        "india_eligibility",
        "employment_category",
        "is_new",
    )
    return [dict(zip(columns, row)) for row in rows]


def _group_jobs(jobs):
    groups = {
        "fresher": [],
        "junior": [],
        "all": list(jobs),
        "india_remote_fresher": [],
        "india_remote_junior": [],
        "india_remote_all": [],
        "india_hybrid": [],
        "india_onsite": [],
        "india_hybrid_onsite": [],
        "globally_restricted": [],
    }
    for job in jobs:
        experience_group = job["experience_group"]
        if experience_group in {"fresher", "junior"}:
            groups[experience_group].append(job)

        india_remote = (
            job["remote_status"] == "fully_remote"
            and job["india_eligibility"] == "eligible"
        )
        if india_remote:
            groups["india_remote_all"].append(job)
            if experience_group in {"fresher", "junior"}:
                groups[f"india_remote_{experience_group}"].append(job)
        if job["employment_category"] in {"India Hybrid", "India Onsite"}:
            groups["india_hybrid_onsite"].append(job)
        if job["employment_category"] == "India Hybrid":
            groups["india_hybrid"].append(job)
        if job["employment_category"] == "India Onsite":
            groups["india_onsite"].append(job)
        if job["india_eligibility"] == "ineligible":
            groups["globally_restricted"].append(job)
    return groups


def _save_snapshot(connection, report_date, groups):
    connection.execute("DELETE FROM daily_skill_metrics WHERE report_date = ?", (report_date,))
    connection.execute(
        "DELETE FROM daily_skill_combinations WHERE report_date = ?",
        (report_date,),
    )
    metrics_by_group = {}
    for group_name, jobs in groups.items():
        metrics = compute_skill_metrics(jobs)
        metrics_by_group[group_name] = metrics
        connection.execute(
            """
            INSERT INTO daily_skill_metrics
            (report_date, group_name, skill, job_count, unique_jobs)
            VALUES (?, ?, '__total__', ?, ?)
            """,
            (
                report_date,
                group_name,
                metrics["unique_jobs"],
                metrics["unique_jobs"],
            ),
        )
        for skill, count in metrics["skills"].items():
            connection.execute(
                """
                INSERT INTO daily_skill_metrics
                (report_date, group_name, skill, job_count, unique_jobs)
                VALUES (?, ?, ?, ?, ?)
                """,
                (report_date, group_name, skill, count, metrics["unique_jobs"]),
            )
        for pair, count in metrics["combinations"].items():
            connection.execute(
                """
                INSERT INTO daily_skill_combinations
                (report_date, group_name, skill_pair, job_count)
                VALUES (?, ?, ?, ?)
                """,
                (report_date, group_name, pair, count),
            )
    return metrics_by_group


def _load_snapshot(connection, report_date, group_name):
    rows = connection.execute(
        """
        SELECT skill, job_count, unique_jobs
        FROM daily_skill_metrics
        WHERE report_date = ? AND group_name = ?
        """,
        (report_date, group_name),
    ).fetchall()
    if not rows:
        return None
    total = next((row[1] for row in rows if row[0] == "__total__"), 0)
    return {
        "unique_jobs": total,
        "skills": {skill: count for skill, count, _ in rows if skill != "__total__"},
    }


def _period_metrics(connection, report_date, offsets, group_name, source_results):
    base_date = date.fromisoformat(report_date)
    report_days = [
        (base_date - timedelta(days=offset)).isoformat()
        for offset in offsets
    ]
    report_days = [
        report_day
        for report_day in report_days
        if _coverage_is_complete(source_results, report_day)
    ]
    if not report_days:
        return compute_skill_metrics([])
    placeholders = ",".join("?" for _ in report_days)
    rows = connection.execute(
        f"""
        SELECT j.dedupe_key, o.skills
        FROM job_observations o
        JOIN jobs j ON j.id = o.job_id
        WHERE o.observed_date IN ({placeholders})
          AND (? = 'all' OR o.experience_group = ?)
        """,
        (*report_days, group_name, group_name),
    ).fetchall()
    skills_by_job = {}
    for key, raw_skills in rows:
        skills_by_job.setdefault(key, set()).update(
            skill.strip()
            for skill in (raw_skills or "").split(",")
            if skill.strip()
        )
    jobs = [
        {"dedupe_key": key, "skills": sorted(skills)}
        for key, skills in skills_by_job.items()
    ]
    return compute_skill_metrics(jobs)


def _trend_lines(connection, report_date, metrics, source_results):
    yesterday = (date.fromisoformat(report_date) - timedelta(days=1)).isoformat()
    rising = []
    declining = []
    if (
        _coverage_is_complete(source_results, report_date)
        and _coverage_is_complete(source_results, yesterday)
    ):
        previous = _load_snapshot(connection, yesterday, "fresher")
        if previous:
            changes = compare_skill_metrics(metrics["fresher"], previous)
            if changes:
                for skill, change in sorted(changes.items(), key=lambda item: item[1], reverse=True):
                    if change > 0:
                        rising.append(f"{skill}: +{change:.0f} points vs yesterday")
                    elif change < 0:
                        declining.append(f"{skill}: {change:.0f} points vs yesterday")

    current_week_days = [
        (date.fromisoformat(report_date) - timedelta(days=offset)).isoformat()
        for offset in range(0, 7)
    ]
    previous_week_days = [
        (date.fromisoformat(report_date) - timedelta(days=offset)).isoformat()
        for offset in range(7, 14)
    ]
    current_week = _period_metrics(
        connection,
        report_date,
        range(0, 7),
        "fresher",
        source_results,
    )
    previous_week = _period_metrics(
        connection,
        report_date,
        range(7, 14),
        "fresher",
        source_results,
    )
    if (
        current_week
        and previous_week
        and sum(_coverage_is_complete(source_results, day) for day in current_week_days) >= 4
        and sum(_coverage_is_complete(source_results, day) for day in previous_week_days) >= 4
        and current_week["unique_jobs"] >= MIN_JOBS_FOR_TREND
        and previous_week["unique_jobs"] >= MIN_JOBS_FOR_TREND
    ):
        changes = compare_skill_metrics(current_week, previous_week)
        if changes:
            weekly_risers = [
                f'{skill}: +{change:.0f} points'
                for skill, change in sorted(changes.items(), key=lambda item: item[1], reverse=True)
                if change > 0
            ]
            rising.extend("7-day: " + item for item in weekly_risers[:3])
            weekly_decliners = [
                f'{skill}: {change:.0f} points'
                for skill, change in sorted(changes.items(), key=lambda item: item[1])
                if change < 0
            ]
            declining.extend("7-day: " + item for item in weekly_decliners[:3])

    current_month_days = [
        (date.fromisoformat(report_date) - timedelta(days=offset)).isoformat()
        for offset in range(0, 30)
    ]
    previous_month_days = [
        (date.fromisoformat(report_date) - timedelta(days=offset)).isoformat()
        for offset in range(30, 60)
    ]
    current_month = _period_metrics(
        connection,
        report_date,
        range(0, 30),
        "fresher",
        source_results,
    )
    previous_month = _period_metrics(
        connection,
        report_date,
        range(30, 60),
        "fresher",
        source_results,
    )
    if (
        current_month["unique_jobs"] >= MIN_JOBS_FOR_TREND
        and previous_month["unique_jobs"] >= MIN_JOBS_FOR_TREND
        and sum(_coverage_is_complete(source_results, day) for day in current_month_days) >= 15
        and sum(_coverage_is_complete(source_results, day) for day in previous_month_days) >= 15
    ):
        changes = compare_skill_metrics(current_month, previous_month)
        if changes:
            monthly_risers = [
                f'{skill}: +{change:.0f} points'
                for skill, change in sorted(changes.items(), key=lambda item: item[1], reverse=True)
                if change > 0
            ]
            rising.extend("30-day: " + item for item in monthly_risers[:3])
            monthly_decliners = [
                f'{skill}: {change:.0f} points'
                for skill, change in sorted(changes.items(), key=lambda item: item[1])
                if change < 0
            ]
            declining.extend("30-day: " + item for item in monthly_decliners[:3])
    return rising[:5], declining[:5]


def _coverage_summary(source_results, report_date):
    sources = source_results.get(report_date, {})
    successful = sorted(
        name
        for name, result in sources.items()
        if not name.startswith("__") and result["success"]
    )
    failures = [
        f"{name}: {result['error'] or 'collection failed'}"
        for name, result in sorted(sources.items())
        if not name.startswith("__") and not result["success"]
    ]
    return successful, failures


def _build_report(connection, report_date):
    jobs = _load_jobs_for_date(connection, report_date)
    groups = _group_jobs(jobs)
    metrics = _save_snapshot(connection, report_date, groups)
    new_eligible = sum(
        1
        for job in jobs
        if job["is_new"]
        and job["experience_group"] in {"fresher", "junior"}
        and job["remote_status"] == "fully_remote"
        and job["india_eligibility"] == "eligible"
    )
    eligible_jobs = len(
        {
            job["dedupe_key"]
            for job in jobs
            if job["experience_group"] in {"fresher", "junior"}
            and job["remote_status"] == "fully_remote"
            and job["india_eligibility"] == "eligible"
        }
    )
    source_results = _latest_source_results(
        connection,
        (date.fromisoformat(report_date) - timedelta(days=59)).isoformat(),
    )
    successful, failures = _coverage_summary(source_results, report_date)
    issues = failures + [
        f"{name}: source not integrated ({detail})"
        for name, detail in SOURCE_LIMITATIONS.items()
    ] + [
        f"{name}: source not integrated ({detail})"
        for name, detail in INDIA_SOURCE_STATUS.items()
    ]
    rising_lines, declining_lines = _trend_lines(
        connection,
        report_date,
        metrics,
        source_results,
    )

    top_skills = sorted(
        metrics["fresher"]["skills"].items(),
        key=lambda item: item[1],
        reverse=True,
    )[:5]
    top_pairs = list(metrics["fresher"]["combinations"].items())[:3]
    recommendations = [
        f"Prioritize {skill}; it appears in {count}/{metrics['fresher']['unique_jobs']} fresher listings."
        for skill, count in top_skills[:3]
    ]
    if not recommendations:
        recommendations = ["Insufficient collected fresher listings for evidence-based recommendations."]
    framework_names = {
        "PyTorch",
        "TensorFlow",
        "scikit-learn",
        "LangChain",
        "Hugging Face",
        "FastAPI",
        "Docker",
        "Kubernetes",
        "MLflow",
        "MLOps",
        "AWS",
        "Azure",
        "GCP",
    }
    framework_counts = sorted(
        (
            (skill, count)
            for skill, count in metrics["all"]["skills"].items()
            if skill in framework_names
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    coverage_text = f"{len(successful)}/{len(EXPECTED_JOB_SOURCES)} configured global job sources succeeded"
    if not successful:
        return None, {
            "sources_checked": 0,
            "issues": issues + ["No job source completed successfully; report not sent."],
        }

    lines = [
        "📊 DAILY AI/ML SKILL INTELLIGENCE",
        "",
        f"Date: {report_date}",
        f"New eligible jobs: {new_eligible}",
        f"Unique eligible jobs analyzed: {eligible_jobs} ({len(jobs)} total AI/ML listings observed)",
        "",
        "TOP FRESHER SKILLS",
    ]
    if top_skills:
        denominator = metrics["fresher"]["unique_jobs"]
        lines.extend(
            f"{index}. {skill} — {count} jobs ({100 * count / denominator:.0f}%)"
            for index, (skill, count) in enumerate(top_skills, start=1)
        )
    else:
        lines.append("No confirmed fresher/graduate AI/ML listings collected today.")

    lines.extend(["", "RISING SKILLS"])
    lines.extend(
        rising_lines
        or ["No comparable increase yet; periods require complete source coverage and at least 5 distinct listings."]
    )
    lines.extend(["", "DECLINING SKILLS"])
    lines.extend(
        declining_lines or ["No supported decline detected in comparable periods."]
    )
    lines.extend(["", "COMMON SKILL COMBINATIONS"])
    lines.extend(
        f"{pair} — {count} fresher listings"
        for pair, count in top_pairs
    )
    if not top_pairs:
        lines.append("Insufficient data.")
    lines.extend(["", "FRAMEWORKS & CLOUD PLATFORMS"])
    lines.extend(
        f"{skill} — {count} of {metrics['all']['unique_jobs']} AI/ML listings"
        for skill, count in framework_counts[:5]
    )
    if not framework_counts:
        lines.append("Insufficient data.")
    lines.extend(
        [
            "",
            "SEGMENT COUNTS",
            (
                f'Fresher/graduate: {metrics["fresher"]["unique_jobs"]}; '
                f'junior (up to 2 years): {metrics["junior"]["unique_jobs"]}; '
                f'all AI/ML: {metrics["all"]["unique_jobs"]}; '
                f'India remote: {metrics["india_remote_all"]["unique_jobs"]}; '
                f'India hybrid: {metrics["india_hybrid"]["unique_jobs"]}; '
                f'India onsite: {metrics["india_onsite"]["unique_jobs"]}; '
                f'India restricted: {metrics["globally_restricted"]["unique_jobs"]}'
            ),
        ]
    )
    lines.extend(["", "WHAT TO LEARN NEXT"])
    lines.extend(recommendations)
    lines.extend(
        [
            "",
            "DATA COVERAGE",
            f"Sources checked: {coverage_text}",
            "Collection issues: " + ("; ".join(issues[:4]) if issues else "None reported"),
            "Comparison period: comparable complete-coverage days only; trends describe listings collected by this bot.",
        ]
    )
    return "\n".join(lines)[:3800], {
        "sources_checked": len(successful),
        "issues": issues,
        "unique_jobs": len(jobs),
        "new_eligible": new_eligible,
    }


def generate_daily_report(path=DB_PATH, report_date=None, send=True):
    initialize_database(path)
    report_date = report_date or datetime.now(LOCAL_TIMEZONE).date().isoformat()
    connection = sqlite3.connect(path)
    try:
        if send and connection.execute(
            "SELECT 1 FROM daily_reports WHERE report_date = ? AND report_type = 'skills'",
            (report_date,),
        ).fetchone():
            return {"already_sent": True, "sources_checked": 0}
        message, metadata = _build_report(connection, report_date)
        connection.commit()
    finally:
        connection.close()

    if not message:
        return metadata
    if send:
        send_telegram_message(message)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                """
                INSERT OR IGNORE INTO daily_reports (report_date, report_type, sent_at)
                VALUES (?, 'skills', ?)
                """,
                (report_date, datetime.now(timezone.utc).isoformat()),
            )
            connection.commit()
        finally:
            connection.close()
    return {"message": message, **metadata}


if __name__ == "__main__":
    result = generate_daily_report()
    if result.get("already_sent"):
        print("Daily skill report already sent for this India-local date.")
    elif result.get("message"):
        print(
            f'Skill report sent; {result.get("new_eligible", 0)} new eligible jobs; '
            f'{result["sources_checked"]} sources succeeded'
        )
    else:
        print("Skill report not sent: no successful job-source checks today.")
