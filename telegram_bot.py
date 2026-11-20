import hmac
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import certifi
import requests

from career_engine import (
    DB_PATH,
    connect_database,
    extract_skills,
    initialize_database,
    normalize_text,
)
from telegram_utils import send_telegram_chat_message, telegram_api_request


LOGGER = logging.getLogger(__name__)
EXPERIENCE_LEVELS = (
    "Fresher / Entry Level",
    "0–2 Years",
    "2–3 Years",
    "3–5 Years",
    "Senior",
    "Internship",
    "Experience not specified",
)
REMOTE_STATUSES = {"fully_remote", "hybrid", "onsite", "unknown"}
INDIA_STATUSES = {"eligible", "ineligible", "unknown"}
APPLICATION_STATUSES = {"Saved", "Applied", "Interview", "Rejected", "Offer", "Dismissed"}
SEARCH_STOP_WORDS = {
    "a", "an", "and", "anywhere", "for", "find", "global", "in", "jobs",
    "me", "of", "remote", "show", "the", "to", "work", "with", "worldwide",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def register_user(profile, chat_id, path=DB_PATH):
    initialize_database(path)
    now = utc_now()
    connection = connect_database(path)
    try:
        connection.execute(
            """
            INSERT INTO telegram_users
                (telegram_user_id, chat_id, username, first_name, last_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                chat_id=excluded.chat_id,
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                updated_at=excluded.updated_at
            """,
            (
                profile["id"],
                chat_id,
                profile.get("username"),
                profile.get("first_name"),
                profile.get("last_name"),
                now,
                now,
            ),
        )
        user_id = connection.execute(
            "SELECT id FROM telegram_users WHERE telegram_user_id = ?",
            (profile["id"],),
        ).fetchone()[0]
        connection.execute(
            "INSERT OR IGNORE INTO user_preferences (user_id) VALUES (?)",
            (user_id,),
        )
        connection.commit()
        return user_id
    finally:
        connection.close()


def enqueue_message(user_id, chat_id, dedupe_key, text, reply_markup=None, path=DB_PATH):
    initialize_database(path)
    now = utc_now()
    connection = connect_database(path)
    try:
        connection.execute(
            """
            INSERT OR IGNORE INTO notification_outbox
                (user_id, dedupe_key, chat_id, text, reply_markup, next_attempt_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                dedupe_key,
                chat_id,
                text[:4000],
                json.dumps(reply_markup, separators=(",", ":")) if reply_markup else None,
                now,
                now,
            ),
        )
        row = connection.execute(
            "SELECT id FROM notification_outbox WHERE user_id = ? AND dedupe_key = ?",
            (user_id, dedupe_key),
        ).fetchone()
        connection.commit()
        return row[0]
    finally:
        connection.close()


def dispatch_pending(path=DB_PATH, limit=20):
    initialize_database(path)
    connection = connect_database(path)
    try:
        connection.execute(
            """
            UPDATE notification_outbox
            SET status = 'pending'
            WHERE status = 'sending' AND next_attempt_at <= ?
            """,
            (utc_now(),),
        )
        connection.commit()
        pending = connection.execute(
            """
            SELECT id, chat_id, text, reply_markup, attempts
            FROM notification_outbox
            WHERE status = 'pending' AND next_attempt_at <= ?
            ORDER BY id
            LIMIT ?
            """,
            (utc_now(), max(1, min(limit, 100))),
        ).fetchall()
    finally:
        connection.close()

    delivered = 0
    for row_id, chat_id, text, markup_json, attempts in pending:
        connection = connect_database(path)
        try:
            cursor = connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'sending',
                    next_attempt_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (
                    (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                    row_id,
                ),
            )
            connection.commit()
            claimed = cursor.rowcount == 1
        finally:
            connection.close()
        if not claimed:
            continue
        try:
            markup = json.loads(markup_json) if markup_json else None
            send_telegram_chat_message(chat_id, text, markup)
        except (requests.RequestException, RuntimeError, ValueError) as error:
            next_attempt = (datetime.now(timezone.utc) + timedelta(
                seconds=min(3600, 30 * (2 ** min(attempts, 7)))
            )).isoformat()
            connection = connect_database(path)
            try:
                connection.execute(
                    """
                    UPDATE notification_outbox
                    SET status = 'pending', attempts = attempts + 1,
                        next_attempt_at = ?, last_error = ?
                    WHERE id = ? AND status = 'sending'
                    """,
                    (next_attempt, str(error)[:500], row_id),
                )
                connection.commit()
            finally:
                connection.close()
            LOGGER.warning("Telegram outbox delivery failed for item %s: %s", row_id, error)
            continue

        connection = connect_database(path)
        try:
            connection.execute(
                """
                UPDATE notification_outbox
                SET status = 'sent', attempts = attempts + 1, sent_at = ?, last_error = NULL
                WHERE id = ? AND status = 'sending'
                """,
                (utc_now(), row_id),
            )
            connection.commit()
        finally:
            connection.close()
        delivered += 1
    return delivered


def deterministic_search_filters(text):
    lowered = normalize_text(text).lower()
    filters = {}
    skills = extract_skills(text)
    if skills:
        filters["skills"] = skills

    if re.search(r"\b(?:fresher|freshers|graduate|new grad|entry[- ]level|junior)\b", lowered):
        filters["experience_level"] = "Fresher / Entry Level"
    elif re.search(r"\b(?:intern|internship)\b", lowered):
        filters["experience_level"] = "Internship"
    elif re.search(r"\b(?:senior|lead|principal|staff)\b", lowered):
        filters["experience_level"] = "Senior"
    elif re.search(r"\b(?:0|zero)\s*(?:-|to)\s*2\s*years?\b", lowered):
        filters["experience_level"] = "0–2 Years"

    if re.search(r"\bhybrid\b", lowered):
        filters["remote_status"] = "hybrid"
    elif re.search(r"\b(?:onsite|on-site|in office)\b", lowered):
        filters["remote_status"] = "onsite"
    elif re.search(r"\b(?:remote|work from home|wfh)\b", lowered):
        filters["remote_status"] = "fully_remote"

    if re.search(r"\bindia\b", lowered):
        filters["india_eligibility"] = (
            "ineligible"
            if re.search(r"\b(?:not|excluding|outside)\s+(?:in\s+)?india\b", lowered)
            else "eligible"
        )
    location_match = re.search(r"\b(?:in|near|based in)\s+([a-z][a-z -]{1,30})", lowered)
    if location_match and "india" not in location_match.group(1):
        location = re.split(
            r"\b(?:with|for|and|remote|hybrid|onsite|jobs?)\b",
            location_match.group(1),
            maxsplit=1,
        )[0].strip()
        if location:
            filters["location"] = location[:60]

    tokens = re.findall(r"[a-z0-9+#.-]+", lowered)
    ignored = SEARCH_STOP_WORDS | {
        "ai", "entry", "level", "freshers", "fresher", "graduate", "junior",
        "intern", "internship", "senior", "lead", "principal", "staff",
        "hybrid", "onsite", "on-site", "india", "remote", "work", "home",
        "wfh", "years", "year",
    }
    ignored.update(skill.lower() for skill in skills)
    ignored.update(word for word in tokens if word.isdigit())
    keywords = " ".join(
        word for word in tokens if word not in ignored and re.search(r"[a-z0-9]", word)
    )
    if keywords:
        filters["keywords"] = keywords[:100]
    return filters


def llm_search_filters(text):
    endpoint = os.getenv("LLM_API_URL")
    api_key = os.getenv("LLM_API_KEY")
    model = os.getenv("LLM_MODEL")
    if not (endpoint and api_key and model):
        return None

    response = requests.post(
        endpoint,
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Convert a job search request into only a JSON object with optional "
                        "string fields: keywords, location, experience_level, remote_status, "
                        "india_eligibility. Allowed remote_status values: fully_remote, hybrid, "
                        "onsite, unknown. Allowed india_eligibility values: eligible, "
                        "ineligible, unknown. Do not invent criteria. Return JSON only."
                    ),
                },
                {"role": "user", "content": text[:500]},
            ],
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=20,
        verify=certifi.where(),
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM search interpretation must be a JSON object")

    allowed = {
        "keywords": 100,
        "location": 60,
        "experience_level": 40,
        "remote_status": 20,
        "india_eligibility": 20,
    }
    result = {}
    for key, maximum in allowed.items():
        value = parsed.get(key)
        if not isinstance(value, str):
            continue
        value = normalize_text(value)[:maximum]
        if value:
            result[key] = value
    if result.get("remote_status") not in REMOTE_STATUSES:
        result.pop("remote_status", None)
    if result.get("india_eligibility") not in INDIA_STATUSES:
        result.pop("india_eligibility", None)
    if result.get("experience_level") not in EXPERIENCE_LEVELS:
        result.pop("experience_level", None)
    return result


def search_jobs(user_id, text, path=DB_PATH):
    initialize_database(path)
    connection = connect_database(path)
    try:
        preferences = connection.execute(
            """
            SELECT desired_skills, location, experience_level, remote_status,
                   india_eligibility, llm_enabled
            FROM user_preferences WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if not preferences:
            raise ValueError("Telegram user preferences are missing")
        filters = deterministic_search_filters(text)
        if preferences[5] and not any(
            key in filters for key in ("skills", "experience_level", "remote_status", "location")
        ):
            try:
                interpreted = llm_search_filters(text)
            except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as error:
                raise ValueError(f"LLM search interpretation failed: {error}") from error
            if interpreted:
                filters.update(interpreted)

        filters.setdefault("experience_level", preferences[2] or "")
        filters.setdefault("remote_status", preferences[3] or "")
        filters.setdefault("india_eligibility", preferences[4] or "")
        filters.setdefault("location", preferences[1] or "")
        if "skills" not in filters and preferences[0]:
            filters["skills"] = [
                skill.strip() for skill in preferences[0].split(",") if skill.strip()
            ]

        conditions = [
            "NOT EXISTS (SELECT 1 FROM user_saved_jobs s "
            "WHERE s.user_id = ? AND s.job_id = jobs.id AND s.status = 'Dismissed')"
        ]
        parameters = [user_id]
        for field in ("experience_level", "remote_status", "india_eligibility"):
            if filters.get(field):
                conditions.append(f"jobs.{field} = ?")
                parameters.append(filters[field])
        if filters.get("location"):
            conditions.append("lower(jobs.location) LIKE lower(?)")
            parameters.append(f"%{filters['location']}%")
        for skill in filters.get("skills", []):
            conditions.append("lower(jobs.skills) LIKE lower(?)")
            parameters.append(f"%{skill}%")
        if filters.get("keywords"):
            for keyword in filters["keywords"].split():
                conditions.append(
                    "(lower(jobs.title) LIKE lower(?) OR lower(jobs.company) LIKE lower(?) "
                    "OR lower(jobs.skills) LIKE lower(?))"
                )
                pattern = f"%{keyword}%"
                parameters.extend((pattern, pattern, pattern))
        rows = connection.execute(
            f"""
            SELECT jobs.id, jobs.title, jobs.company, jobs.location, jobs.score,
                   jobs.experience_level, jobs.remote_status, jobs.india_eligibility,
                   jobs.skills, jobs.application_url, jobs.listing_url
            FROM jobs
            WHERE {' AND '.join(conditions)}
            ORDER BY COALESCE(jobs.score, 0) DESC, jobs.created_at DESC
            LIMIT 5
            """,
            parameters,
        ).fetchall()
        return [dict(zip(
            ("id", "title", "company", "location", "score", "experience_level",
             "remote_status", "india_eligibility", "skills", "application_url", "listing_url"),
            row,
        )) for row in rows]
    finally:
        connection.close()


def job_keyboard(job):
    rows = [[
        {"text": "Save", "callback_data": f"save:{job['id']}"},
        {"text": "Dismiss", "callback_data": f"dismiss:{job['id']}"},
    ]]
    link = job.get("application_url") or job.get("listing_url")
    if link and link.startswith(("https://", "http://")):
        rows.append([{"text": "Apply", "url": link}])
    return {"inline_keyboard": rows}


def job_message(job):
    return (
        f"💼 {job['title']}\n"
        f"🏢 {job.get('company') or 'Company not specified'}\n"
        f"📍 {job.get('location') or 'Location not specified'}\n"
        f"🎯 {job.get('experience_level') or 'Experience not specified'} · "
        f"{job.get('remote_status') or 'unknown'} · India {job.get('india_eligibility') or 'unknown'}\n"
        f"⭐ Match score: {job.get('score') if job.get('score') is not None else 'Not scored'}"
    )


def update_saved_job(user_id, job_id, status, path=DB_PATH):
    if status not in APPLICATION_STATUSES:
        raise ValueError("Unsupported saved-job status")
    initialize_database(path)
    connection = connect_database(path)
    try:
        if not connection.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone():
            return False
        now = utc_now()
        connection.execute(
            """
            INSERT INTO user_saved_jobs (user_id, job_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, job_id) DO UPDATE SET
                status=excluded.status, updated_at=excluded.updated_at
            """,
            (user_id, job_id, status, now, now),
        )
        connection.commit()
        return True
    finally:
        connection.close()


def saved_jobs(user_id, path=DB_PATH):
    connection = connect_database(path)
    try:
        return connection.execute(
            """
            SELECT jobs.id, jobs.title, jobs.company, jobs.application_url,
                   jobs.listing_url, s.status
            FROM user_saved_jobs s JOIN jobs ON jobs.id = s.job_id
            WHERE s.user_id = ? AND s.status != 'Dismissed'
            ORDER BY s.updated_at DESC LIMIT 20
            """,
            (user_id,),
        ).fetchall()
    finally:
        connection.close()


def update_preference(user_id, name, value, path=DB_PATH):
    valid_fields = {
        "skills": ("desired_skills", None),
        "location": ("location", None),
        "experience": ("experience_level", EXPERIENCE_LEVELS),
        "remote": ("remote_status", REMOTE_STATUSES),
        "india": ("india_eligibility", INDIA_STATUSES),
    }
    connection = connect_database(path)
    try:
        if name == "alerts":
            normalized = value.lower()
            if normalized not in {"on", "off", "yes", "no", "true", "false", "1", "0"}:
                raise ValueError("alerts must be on or off")
            enabled = normalized in {"on", "yes", "true", "1"}
            connection.execute(
                "UPDATE user_preferences SET alerts_enabled = ? WHERE user_id = ?",
                (int(enabled), user_id),
            )
            if enabled:
                connection.execute(
                    "UPDATE telegram_users SET unsubscribed_at = NULL WHERE id = ?",
                    (user_id,),
                )
        elif name == "llm":
            normalized = value.lower()
            if normalized not in {"on", "off", "yes", "no", "true", "false", "1", "0"}:
                raise ValueError("llm must be on or off")
            enabled = normalized in {"on", "yes", "true", "1"}
            connection.execute(
                "UPDATE user_preferences SET llm_enabled = ? WHERE user_id = ?",
                (int(enabled), user_id),
            )
        elif name in valid_fields:
            column, choices = valid_fields[name]
            normalized = "" if value.lower() in {"none", "off", "clear"} else normalize_text(value)
            if choices and normalized not in choices:
                raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
            if name == "skills":
                normalized = ", ".join(extract_skills(normalized)) or normalized[:200]
            connection.execute(
                f"UPDATE user_preferences SET {column} = ? WHERE user_id = ?",
                (normalized[:200], user_id),
            )
        else:
            raise ValueError("Unknown preference")
        connection.commit()
    finally:
        connection.close()


def preference_summary(user_id, path=DB_PATH):
    connection = connect_database(path)
    try:
        row = connection.execute(
            """
            SELECT desired_skills, location, experience_level, remote_status,
                   india_eligibility, alerts_enabled, llm_enabled
            FROM user_preferences WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if not row:
            raise ValueError("Telegram user preferences are missing")
        return (
            f"Skills: {row[0] or 'any'}\nLocation: {row[1] or 'any'}\n"
            f"Experience: {row[2] or 'any'}\nRemote: {row[3] or 'any'}\n"
            f"India eligibility: {row[4] or 'any'}\n"
            f"Alerts: {'on' if row[5] else 'off'}\n"
            f"LLM search fallback: {'on' if row[6] else 'off'}"
        )
    finally:
        connection.close()


def _process_message(message, user_id, chat_id, update_id, path):
    text = normalize_text(message.get("text", ""))
    if not text:
        enqueue_message(user_id, chat_id, f"update:{update_id}:help", "Send a text search or /help.", path=path)
        return
    command, _, argument = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    key = f"update:{update_id}"

    if command in {"/start", "/subscribe"}:
        connection = connect_database(path)
        try:
            connection.execute(
                "UPDATE telegram_users SET unsubscribed_at = NULL WHERE id = ?", (user_id,)
            )
            connection.execute(
                "UPDATE user_preferences SET alerts_enabled = 1 WHERE user_id = ?", (user_id,)
            )
            connection.commit()
        finally:
            connection.close()
        reply = (
            "Welcome! Send a search such as “show fresher remote Python jobs in India”. "
            "Use /prefs to set defaults and /help to see commands."
        )
    elif command == "/help":
        reply = (
            "/search <query> — search collected jobs\n"
            "/prefs — view preferences\n"
            "/prefs skills|location|experience|remote|india <value> — set a filter\n"
            "/prefs alerts on|off — control alerts\n"
            "/prefs llm on|off — opt in/out of external LLM interpretation\n"
            "/saved — list saved jobs\n"
            "/track <job_id> — mark a job as applied\n"
            "/unsubscribe — stop personalized alerts\n"
            "You can also send a search in plain language."
        )
    elif command == "/unsubscribe":
        connection = connect_database(path)
        try:
            connection.execute(
                "UPDATE telegram_users SET unsubscribed_at = ? WHERE id = ?",
                (utc_now(), user_id),
            )
            connection.execute(
                "UPDATE user_preferences SET alerts_enabled = 0 WHERE user_id = ?",
                (user_id,),
            )
            connection.commit()
        finally:
            connection.close()
        reply = "Personalized job alerts are off. Send /start to turn them back on."
    elif command == "/prefs":
        if not argument:
            reply = preference_summary(user_id, path)
        else:
            name, _, value = argument.partition(" ")
            if not value:
                raise ValueError("Use /prefs <field> <value>. See /help.")
            update_preference(user_id, name.lower(), value, path)
            reply = "Preference saved."
            if name.lower() == "llm" and value.lower() == "on":
                reply += (
                    " Search text may be sent to the configured LLM provider when "
                    "deterministic parsing is insufficient."
                )
    elif command == "/saved":
        items = saved_jobs(user_id, path)
        if not items:
            reply = "No saved jobs yet. Use /search and tap Save."
        else:
            for job_id, title, company, application_url, listing_url, status in items:
                keyboard = {"inline_keyboard": [[
                    {"text": status, "callback_data": f"track:{job_id}"},
                    {"text": "Remove", "callback_data": f"remove:{job_id}"},
                    *([{"text": "Apply", "url": application_url or listing_url}]
                      if (application_url or listing_url) else []),
                ]]}
                enqueue_message(
                    user_id,
                    chat_id,
                    f"{key}:saved:{job_id}",
                    f"{title}\n{company or 'Company not specified'}",
                    keyboard,
                    path,
                )
            return
    elif command == "/track":
        if not argument.isdigit():
            raise ValueError("Use /track <job_id>.")
        if not update_saved_job(user_id, int(argument), "Applied", path):
            raise ValueError("Job not found.")
        reply = "Application marked as applied."
    else:
        query = argument if command == "/search" else text
        if command.startswith("/"):
            reply = "Unknown command. Use /help."
        else:
            jobs = search_jobs(user_id, query, path)
            if not jobs:
                reply = "No matching jobs found in the collected listings. Try broader filters or update /prefs."
            else:
                for job in jobs:
                    enqueue_message(
                        user_id,
                        chat_id,
                        f"{key}:job:{job['id']}",
                        job_message(job),
                        job_keyboard(job),
                        path,
                    )
                return

    enqueue_message(user_id, chat_id, f"{key}:reply", reply, path=path)


def _process_callback(callback, user_id, chat_id, update_id, path):
    callback_id = callback.get("id", "")
    data = callback.get("data", "")
    action, separator, identifier = data.partition(":")
    if not separator or not identifier.isdigit():
        raise ValueError("Invalid job action")
    job_id = int(identifier)
    messages = {
        "save": ("Saved", "Job saved."),
        "track": ("Applied", "Application marked as applied."),
        "dismiss": ("Dismissed", "Job dismissed."),
    }
    if action == "remove":
        connection = connect_database(path)
        try:
            connection.execute(
                "DELETE FROM user_saved_jobs WHERE user_id = ? AND job_id = ?",
                (user_id, job_id),
            )
            connection.commit()
        finally:
            connection.close()
        reply = "Job removed from your saved list."
    elif action in messages:
        status, reply = messages[action]
        if not update_saved_job(user_id, job_id, status, path):
            raise ValueError("Job not found.")
    else:
        raise ValueError("Unsupported job action")

    telegram_api_request("answerCallbackQuery", {"callback_query_id": callback_id, "text": reply})
    enqueue_message(
        user_id,
        chat_id,
        f"update:{update_id}:callback",
        reply,
        path=path,
    )


def process_telegram_update(update, path=DB_PATH):
    initialize_database(path)
    update_id = update.get("update_id")
    if not isinstance(update_id, int):
        raise ValueError("Telegram update has no valid update_id")
    connection = connect_database(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT status, updated_at FROM telegram_updates WHERE update_id = ?",
            (update_id,),
        ).fetchone()
        if existing and existing[0] == "processed":
            connection.rollback()
            return False
        if existing and existing[0] == "processing":
            try:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(existing[1])
            except ValueError:
                age = timedelta(minutes=11)
            if age < timedelta(minutes=10):
                connection.rollback()
                return False
        connection.execute(
            """
            INSERT INTO telegram_updates (update_id, status, updated_at)
            VALUES (?, 'processing', ?)
            ON CONFLICT(update_id) DO UPDATE SET status='processing', updated_at=excluded.updated_at
            """,
            (update_id, utc_now()),
        )
        connection.commit()
    finally:
        connection.close()

    try:
        message = update.get("message")
        callback = update.get("callback_query")
        payload = callback or message
        if not payload:
            raise ValueError("Unsupported Telegram update type")
        profile = payload.get("from")
        chat = payload.get("message", {}).get("chat", {}) if callback else payload.get("chat", {})
        if not isinstance(profile, dict) or not isinstance(profile.get("id"), int):
            raise ValueError("Telegram update has no valid user")
        if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
            raise ValueError("Telegram update has no valid chat")
        user_id = register_user(profile, chat["id"], path)
        try:
            if callback:
                _process_callback(callback, user_id, chat["id"], update_id, path)
            else:
                _process_message(message, user_id, chat["id"], update_id, path)
        except ValueError as error:
            enqueue_message(
                user_id,
                chat["id"],
                f"update:{update_id}:error",
                f"Sorry, {error}",
                path=path,
            )

        connection = connect_database(path)
        try:
            connection.execute(
                "UPDATE telegram_updates SET status = 'processed', updated_at = ? WHERE update_id = ?",
                (utc_now(), update_id),
            )
            connection.commit()
        finally:
            connection.close()
        dispatch_pending(path)
        return True
    except Exception:
        connection = connect_database(path)
        try:
            connection.execute(
                "UPDATE telegram_updates SET status = 'failed', updated_at = ? WHERE update_id = ?",
                (utc_now(), update_id),
            )
            connection.commit()
        finally:
            connection.close()
        raise


def enqueue_job_alerts(job, path=DB_PATH):
    initialize_database(path)
    connection = connect_database(path)
    try:
        row = connection.execute(
            "SELECT id FROM jobs WHERE dedupe_key = ?",
            (job["analysis"]["dedupe_key"],),
        ).fetchone()
        if not row:
            return 0
        job_id = row[0]
        users = connection.execute(
            """
            SELECT u.id, u.chat_id, p.desired_skills, p.location, p.experience_level,
                   p.remote_status, p.india_eligibility
            FROM telegram_users u JOIN user_preferences p ON p.user_id = u.id
            WHERE u.unsubscribed_at IS NULL AND p.alerts_enabled = 1
            """
        ).fetchall()
    finally:
        connection.close()

    skills = {skill.strip().lower() for skill in job["analysis"]["skills"]}
    delivered_to = []
    for user in users:
        user_id, chat_id, skill_pref, location, experience, remote, india = user
        preferred_skills = {value.strip().lower() for value in (skill_pref or "").split(",") if value.strip()}
        if preferred_skills and not preferred_skills.intersection(skills):
            continue
        if location and location.lower() not in str(job.get("location", "")).lower():
            continue
        if experience and experience != job.get("experience_level"):
            continue
        if remote and remote != job.get("remote_status"):
            continue
        if india and india != job.get("india_eligibility"):
            continue

        record = {
            "id": job_id,
            "application_url": job.get("application_link"),
            "listing_url": job.get("link"),
        }
        enqueue_message(
            user_id,
            chat_id,
            f"job:{job_id}",
            job_message({
                **record,
                **job,
                "score": job["analysis"]["score"],
                "experience_level": job.get("experience_level"),
            }),
            job_keyboard(record),
            path,
        )
        delivered_to.append(user_id)
    dispatch_pending(path)
    return len(delivered_to)


def verify_webhook_secret(provided):
    configured = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    return bool(configured and provided and hmac.compare_digest(configured, provided))


def set_webhook(url):
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("Set TELEGRAM_WEBHOOK_SECRET before configuring a webhook")
    parsed_url = urlsplit(url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise ValueError("Telegram webhook URL must be an absolute HTTPS URL")
    return telegram_api_request(
        "setWebhook",
        {"url": url, "secret_token": secret, "allowed_updates": ["message", "callback_query"]},
    )


def set_bot_commands():
    return telegram_api_request(
        "setMyCommands",
        {
            "commands": [
                {"command": "start", "description": "Start or re-enable job alerts"},
                {"command": "search", "description": "Search collected job listings"},
                {"command": "prefs", "description": "View or update your job preferences"},
                {"command": "saved", "description": "View saved jobs"},
                {"command": "track", "description": "Mark a job as applied"},
                {"command": "unsubscribe", "description": "Stop personalized job alerts"},
                {"command": "help", "description": "Show chatbot commands"},
            ]
        },
    )
