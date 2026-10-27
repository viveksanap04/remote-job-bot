""" import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN=os.getenv("BOT_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")

url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

data={
    "chat_id":CHAT_ID,
    "text":"Telegram bot is working successfully!"
}

response=requests.post(url,data=data)

print(response.json())
 """

import os
from pathlib import Path

import certifi
import requests

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().with_name(".env"))


BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
if not BOT_TOKEN or not CHAT_ID:
    missing = [
        name for name, value in (("BOT_TOKEN", BOT_TOKEN), ("CHAT_ID", CHAT_ID)) if not value
    ]
    raise SystemExit("Missing Telegram configuration: " + ", ".join(missing))


url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


data = {
    "chat_id": CHAT_ID,
    "text": "Telegram SSL test successful!",
}


response=requests.post(
    url,
    data=data,
    timeout=15,
    verify=certifi.where(),
)

response.raise_for_status()
result = response.json()
if not result.get("ok"):
    raise SystemExit(f"Telegram rejected the test message: {result.get('description', 'Unknown error')}")

print(result)