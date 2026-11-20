import os
import time
from pathlib import Path

import certifi
import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().with_name(".env"))


def telegram_api_request(method, payload, attempts=3):
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Missing Telegram configuration: BOT_TOKEN. "
            "Set this in the repository .env file or GitHub Actions secrets."
        )

    url = f"https://api.telegram.org/bot{token}/{method}"
    for attempt in range(max(1, attempts)):
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=15,
                verify=certifi.where(),
            )
            response.raise_for_status()
            result = response.json()
            if not result.get("ok"):
                raise RuntimeError(
                    "Telegram rejected the request: "
                    + result.get("description", "Unknown error")
                )
            return result
        except requests.RequestException:
            if attempt < max(1, attempts) - 1:
                time.sleep(2**attempt)

    raise RuntimeError(
        f"Unable to call Telegram {method} after {max(1, attempts)} attempts; "
        "check network access and Telegram configuration."
    ) from None


def telegram_api_get(method, parameters=None, timeout=15):
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "Missing Telegram configuration: BOT_TOKEN. "
            "Set this in the repository .env file or GitHub Actions secrets."
        )
    response = requests.get(
        f"https://api.telegram.org/bot{token}/{method}",
        params=parameters or {},
        timeout=timeout,
        verify=certifi.where(),
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(
            "Telegram rejected the request: "
            + result.get("description", "Unknown error")
        )
    return result


def send_telegram_chat_message(chat_id, message, reply_markup=None):
    payload = {"chat_id": chat_id, "text": message}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return telegram_api_request("sendMessage", payload)


def send_telegram_message(message):
    chat_id = os.getenv("CHAT_ID")
    if not chat_id:
        raise RuntimeError(
            "Missing Telegram configuration: CHAT_ID. "
            "Set this in the repository .env file or GitHub Actions secrets."
        )
    return send_telegram_chat_message(chat_id, message)
