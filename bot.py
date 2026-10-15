"""Телеграм-бот проекта techcrunch-reels.

Всем: /news — свежие новости TechCrunch, /history — что уже присылал.
Только владельцу: любое сообщение без «/» — задача для Claude Code на ноутбуке.
Задачи, пришедшие, пока бот был выключен, выполняются только после подтверждения (/run).

Запуск: py bot.py. Настройки в файле .env:
    TELEGRAM_BOT_TOKEN=...      токен от @BotFather
    TELEGRAM_OWNER=username     ник владельца в Telegram без @
Работает, пока запущена программа. Дополнительные пакеты не нужны.
"""

import html
import json
import os
import queue
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import storage
from fetch_news import load_items, pick

HERE = Path(__file__).parent
MAX_NEWS = 7
TASK_TIMEOUT = 20 * 60
CLAUDE = Path.home() / ".local" / "bin" / "claude.exe"
STYLE_DIR = Path(r"C:\Users\Anita\Desktop\Claude перенос\Для ChatGPT\02 Виральный контент\Сценарии видео")
# Что Claude может делать по задаче из Telegram: читать, искать в интернете, писать файлы
# в проекте и собирать новости. Остальные команды без подтверждения в этом режиме запрещены.
ALLOWED_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "Write", "Edit",
                 "Bash(py fetch_news.py)", "Bash(py fetch_news.py *)",
                 "PowerShell(py fetch_news.py)", "PowerShell(py fetch_news.py *)"]

HELP_TEXT = (
    "Привет! Я присылаю свежие новости TechCrunch про ИИ, стартапы, финтех и технологии — "
    "материал для коротких роликов.\n\n"
    "/news — свежие новости за последние сутки\n"
    "/history — какие новости я уже присылал (хранятся в базе)\n"
    "/start — это сообщение"
)
OWNER_HELP = (
    "\n\nВам как владельцу: напишите задачу обычным сообщением, и Claude на ноутбуке её выполнит.\n"
    "/tasks — задачи, которые ждут подтверждения\n"
    "/run — выполнить их\n"
    "/skip — отменить их"
)


def read_env():
    values = {}
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    if "TELEGRAM_BOT_TOKEN" not in values:
        raise SystemExit("В файле .env нет строки TELEGRAM_BOT_TOKEN=...")
    return values


ENV = read_env()
API = f"https://api.telegram.org/bot{ENV['TELEGRAM_BOT_TOKEN']}/"
OWNER = ENV.get("TELEGRAM_OWNER", "").lstrip("@").lower()


def call(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API + method, data=data, timeout=60) as response:
        return json.loads(response.read())["result"]


def reply(chat_id, text, html_mode=True):
    params = {"chat_id": chat_id, "disable_web_page_preview": "true"}
    if html_mode:
        params["parse_mode"] = "HTML"
    # Telegram принимает до 4096 символов в одном сообщении
    for start in range(0, max(len(text), 1), 4000):
        call("sendMessage", text=text[start:start + 4000], **params)


def news_message():
    items = list(load_items())
    hours = 24
    chosen = pick(items, hours)
    if not chosen:
        hours = 72
        chosen = pick(items, hours)
    if not chosen:
        return "За последние трое суток подходящих новостей на TechCrunch нет."

    chosen = chosen[:MAX_NEWS]
    new_links = storage.remember(chosen)

    lines = [f"<b>Свежее на TechCrunch за {hours} ч</b>", ""]
    for item in chosen:
        date = item["published"].astimezone().strftime("%d.%m %H:%M")
        title = html.escape(item["title"])
        mark = "🆕" if item["link"] in new_links else "↩️"
        lines.append(f'{mark} <a href="{item["link"]}">{title}</a> — {date}')
    lines += [
        "",
        f"🆕 новых: {len(new_links)}, ↩️ уже присылал: {len(chosen) - len(new_links)}",
        "Дату самого события проверяйте отдельно перед съёмкой.",
    ]
    return "\n".join(lines)


def history_message():
    total, rows = storage.history()
    if not total:
        return "В базе пока пусто. Напишите /news, и я начну запоминать новости."
    lines = [f"<b>В базе {total} новостей.</b> Последние:", ""]
    for title, link, sent_at in rows:
        lines.append(f'• <a href="{link}">{html.escape(title)}</a> — впервые прислал {sent_at}')
    return "\n".join(lines)


# ---------- Задачи для Claude ----------

work = queue.Queue()


def run_claude(text):
    prompt = (
        "Задача от Ани, отправленная через Telegram-бота проекта:\n\n"
        f"{text}\n\n"
        "Выполни её. Свежие новости собирай ровно командой `py fetch_news.py` без добавок "
        "(результат в candidates.md). Ответ пойдёт в Telegram: пиши по-русски, простыми словами, без таблиц и "
        "markdown-разметки, не длиннее 3500 символов. Если задача про сценарий — следуй CLAUDE.md "
        f"и правилам стиля из папки {STYLE_DIR}. Если для задачи нужно то, что тебе здесь "
        "запрещено, скажи, что сделаешь это в приложении Claude."
    )
    command = [str(CLAUDE), "-p", prompt, "--output-format", "text",
               "--add-dir", str(STYLE_DIR), "--allowedTools", *ALLOWED_TOOLS]
    result = subprocess.run(command, cwd=HERE, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=TASK_TIMEOUT,
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    output = (result.stdout or "").strip()
    if result.returncode != 0 or not output:
        raise RuntimeError((result.stderr or output or "пустой ответ").strip()[:500])
    return output


def worker():
    while True:
        task_id, chat_id, text = work.get()
        storage.set_task(task_id, "running")
        print(f"Задача {task_id}: начинаю")
        try:
            answer = run_claude(text)
            storage.set_task(task_id, "done", answer)
            reply(chat_id, f"✅ Задача {task_id} готова:\n\n{answer}", html_mode=False)
        except Exception as error:
            storage.set_task(task_id, "failed", str(error))
            reply(chat_id, f"⚠️ Задачу {task_id} выполнить не получилось: {error}", html_mode=False)
        print(f"Задача {task_id}: завершена")


def enqueue(task_id, chat_id, text):
    storage.set_task(task_id, "queued")
    work.put((task_id, chat_id, text))


def waiting_message():
    waiting = storage.tasks_with_status("waiting")
    if not waiting:
        return "Задач, ждущих подтверждения, нет."
    lines = [f"Пока я был выключен, пришло задач: {len(waiting)}.", ""]
    for task_id, _, text, received_at in waiting:
        short = text if len(text) <= 120 else text[:120] + "…"
        lines.append(f"{task_id}. ({received_at}) {short}")
    lines += ["", "Выполнить? /run — да, все. /skip — отменить."]
    return "\n".join(lines)


def is_owner(message):
    return bool(OWNER) and (message.get("from", {}).get("username") or "").lower() == OWNER


def handle(message, started_at):
    chat_id = message["chat"]["id"]
    raw = message.get("text", "").strip()
    text = raw.lower()
    owner = is_owner(message)

    if text.startswith("/news"):
        reply(chat_id, "Собираю свежие новости…")
        try:
            reply(chat_id, news_message())
        except Exception as error:
            reply(chat_id, "Не получилось загрузить новости TechCrunch, попробуйте чуть позже.")
            print("Ошибка при сборе новостей:", error)
    elif text.startswith("/history"):
        reply(chat_id, history_message())
    elif owner and text.startswith("/tasks"):
        reply(chat_id, waiting_message(), html_mode=False)
    elif owner and text.startswith("/run"):
        waiting = storage.tasks_with_status("waiting")
        for task_id, task_chat, task_text, _ in waiting:
            enqueue(task_id, task_chat, task_text)
        reply(chat_id, f"Запускаю задач: {len(waiting)}. Пришлю результат каждой." if waiting
              else "Задач, ждущих подтверждения, нет.", html_mode=False)
    elif owner and text.startswith("/skip"):
        waiting = storage.tasks_with_status("waiting")
        for task_id, *_ in waiting:
            storage.set_task(task_id, "skipped")
        reply(chat_id, f"Отменил задач: {len(waiting)}.", html_mode=False)
    elif owner and raw and not raw.startswith("/"):
        received = datetime.fromtimestamp(message["date"]).strftime("%Y-%m-%d %H:%M")
        if message["date"] < started_at:
            # Пришло, пока бот был выключен: ждём подтверждения, сводку пришлём после пачки
            storage.add_task(chat_id, raw, received, "waiting")
            return "waiting"
        task_id = storage.add_task(chat_id, raw, received, "queued")
        ahead = work.qsize()
        work.put((task_id, chat_id, raw))
        reply(chat_id, f"Принято, задача {task_id}. Работаю…" +
              (f" Передо мной в очереди ещё {ahead}." if ahead else ""), html_mode=False)
    elif raw and not raw.startswith("/"):
        reply(chat_id, "Задачи я принимаю только от владельца бота. Попробуйте /news.", html_mode=False)
    else:
        reply(chat_id, HELP_TEXT + (OWNER_HELP if owner else ""))
    return None


def main():
    call("setMyCommands", commands=json.dumps([
        {"command": "news", "description": "Свежие новости TechCrunch"},
        {"command": "history", "description": "Какие новости уже присылал"},
        {"command": "tasks", "description": "Задачи, ждущие подтверждения"},
        {"command": "run", "description": "Выполнить ждущие задачи"},
        {"command": "skip", "description": "Отменить ждущие задачи"},
        {"command": "start", "description": "Что умеет бот"},
    ]))
    me = call("getMe")
    started_at = time.time()
    threading.Thread(target=worker, daemon=True).start()
    print(f"Бот @{me['username']} запущен. Владелец: @{OWNER or 'не задан'}. "
          "Чтобы остановить, закройте это окно.")

    # Задачи, оставшиеся в очереди с прошлого запуска, тоже требуют подтверждения
    for task_id, *_ in storage.tasks_with_status("queued") + storage.tasks_with_status("running"):
        storage.set_task(task_id, "waiting")
    for chat_id in {row[1] for row in storage.tasks_with_status("waiting")}:
        reply(chat_id, waiting_message(), html_mode=False)

    offset = 0
    while True:
        try:
            # Telegram держит запрос до 30 секунд, пока не придёт новое сообщение
            updates = call("getUpdates", offset=offset, timeout=30)
        except Exception as error:
            print("Нет связи с Telegram, повторяю через 5 секунд:", error)
            time.sleep(5)
            continue
        new_waiting = {}
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message")
            if message:
                print("Сообщение от", message["chat"].get("username") or message["chat"]["id"],
                      ":", message.get("text", ""))
                try:
                    if handle(message, started_at) == "waiting":
                        new_waiting[message["chat"]["id"]] = True
                except Exception as error:
                    print("Ошибка при обработке сообщения:", error)
        for chat_id in new_waiting:
            reply(chat_id, waiting_message(), html_mode=False)


if __name__ == "__main__":
    main()
