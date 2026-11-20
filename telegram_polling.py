import argparse
import logging
import time

from career_engine import DB_PATH, connect_database, initialize_database
from telegram_bot import (
    dispatch_pending,
    process_telegram_update,
    set_bot_commands,
    set_webhook,
)
from telegram_utils import telegram_api_get, telegram_api_request


LOGGER = logging.getLogger("telegram_polling")


def stored_offset(path=DB_PATH):
    connection = connect_database(path)
    try:
        row = connection.execute(
            "SELECT value FROM telegram_runtime_state WHERE key = 'polling_offset'"
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        connection.close()


def save_offset(offset, path=DB_PATH):
    connection = connect_database(path)
    try:
        connection.execute(
            """
            INSERT INTO telegram_runtime_state (key, value) VALUES ('polling_offset', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(offset),),
        )
        connection.commit()
    finally:
        connection.close()


def poll_once(path=DB_PATH, timeout=30):
    offset = stored_offset(path)
    result = telegram_api_get(
        "getUpdates",
        {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": '["message","callback_query"]',
        },
        timeout=timeout + 10,
    )
    updates = result.get("result")
    if not isinstance(updates, list):
        raise RuntimeError("Telegram getUpdates returned an unexpected response")
    for update in updates:
        process_telegram_update(update, path)
        save_offset(update["update_id"] + 1, path)
    dispatch_pending(path)
    return len(updates)


def run_polling(path=DB_PATH):
    initialize_database(path)
    LOGGER.info("Telegram long-polling worker started")
    while True:
        try:
            poll_once(path)
        except KeyboardInterrupt:
            raise
        except Exception:
            LOGGER.exception("Telegram polling iteration failed")
            time.sleep(5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Telegram chatbot polling worker.")
    parser.add_argument("--set-webhook", help="Configure Telegram webhook using this public HTTPS URL.")
    parser.add_argument(
        "--set-commands",
        action="store_true",
        help="Register the supported commands in Telegram's bot menu.",
    )
    parser.add_argument(
        "--clear-webhook",
        action="store_true",
        help="Delete the configured Telegram webhook before polling.",
    )
    parser.add_argument("--once", action="store_true", help="Process one long-polling batch and exit.")
    arguments = parser.parse_args(argv)
    if arguments.set_commands:
        set_bot_commands()
        print("Telegram bot commands registered.")
        return 0
    if arguments.set_webhook:
        set_webhook(arguments.set_webhook)
        print("Telegram webhook configured.")
        return 0
    initialize_database()
    if arguments.clear_webhook:
        telegram_api_request("deleteWebhook", {"drop_pending_updates": False})
    if arguments.once:
        print(f"Processed {poll_once()} Telegram update(s).")
        return 0
    run_polling()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
