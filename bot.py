"""Телеграм-бот: по команде /news присылает свежие новости TechCrunch по темам блога.

Запуск: python bot.py   (токен берётся из файла .env: TELEGRAM_BOT_TOKEN=...)
Работает, пока запущена программа. Дополнительные пакеты не нужны.
"""

import html
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

from fetch_news import load_items, pick

MAX_NEWS = 7
HELP_TEXT = (
    "Привет! Я присылаю свежие новости TechCrunch про ИИ, стартапы, финтех и технологии — "
    "материал для коротких роликов.\n\n"
    "/news — свежие новости за последние сутки\n"
    "/start — это сообщение"
)


def read_token():
    env = Path(__file__).with_name(".env")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("В файле .env нет строки TELEGRAM_BOT_TOKEN=...")


API = f"https://api.telegram.org/bot{read_token()}/"


def call(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API + method, data=data, timeout=60) as response:
        return json.loads(response.read())["result"]


def news_message():
    items = list(load_items())
    hours = 24
    chosen = pick(items, hours)
    if not chosen:
        hours = 72
        chosen = pick(items, hours)
    if not chosen:
        return "За последние трое суток подходящих новостей на TechCrunch нет."

    lines = [f"<b>Свежее на TechCrunch за {hours} ч</b>", ""]
    for item in chosen[:MAX_NEWS]:
        date = item["published"].astimezone().strftime("%d.%m %H:%M")
        title = html.escape(item["title"])
        lines.append(f'• <a href="{item["link"]}">{title}</a> — {date}')
    lines += ["", "Дату самого события проверяйте отдельно перед съёмкой."]
    return "\n".join(lines)


def reply(chat_id, text):
    call("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
         disable_web_page_preview="true")


def handle(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip().lower()
    if text.startswith("/news"):
        reply(chat_id, "Собираю свежие новости…")
        try:
            reply(chat_id, news_message())
        except Exception as error:
            reply(chat_id, "Не получилось загрузить новости TechCrunch, попробуйте чуть позже.")
            print("Ошибка при сборе новостей:", error)
    else:
        reply(chat_id, HELP_TEXT)


def main():
    call("setMyCommands", commands=json.dumps([
        {"command": "news", "description": "Свежие новости TechCrunch"},
        {"command": "start", "description": "Что умеет бот"},
    ]))
    me = call("getMe")
    print(f"Бот @{me['username']} запущен. Чтобы остановить, закройте это окно.")

    offset = 0
    while True:
        try:
            # Telegram держит запрос до 30 секунд, пока не придёт новое сообщение
            updates = call("getUpdates", offset=offset, timeout=30)
        except Exception as error:
            print("Нет связи с Telegram, повторяю через 5 секунд:", error)
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if message:
                print("Сообщение от", message["chat"].get("username") or message["chat"]["id"],
                      ":", message.get("text", ""))
                handle(message)


if __name__ == "__main__":
    main()
