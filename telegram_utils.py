import os
import time
from pathlib import Path

import certifi
import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().with_name(".env"))


def send_telegram_message(message):
    token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID")
    missing = [
        name
        for name, value in (("BOT_TOKEN", token), ("CHAT_ID", chat_id))
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing Telegram configuration: "
            + ", ".join(missing)
            + ". Set these in the repository .env file or GitHub Actions secrets."
        )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": message},
                timeout=15,
                verify=certifi.where(),
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                raise RuntimeError(
                    "Telegram rejected the message: "
                    + result.get("description", "Unknown error")
                )
            return result
        except requests.RequestException:
            if attempt < 2:
                time.sleep(2**attempt)

    raise RuntimeError(
        "Unable to send Telegram message after 3 attempts; "
        "check network access and Telegram configuration."
    ) from None
