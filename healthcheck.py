"""Проверка здоровья проекта: находит поломки, простые чинит сам, пишет Ане в Telegram.

    py healthcheck.py               проверить всё
    py healthcheck.py --notify ТЕКСТ отправить владельцу сообщение (для агента)

Код выхода: 0 — всё в порядке (никому не пишем), 1 — что-то починено и отчёт отправлен,
2 — нужна помощь агента (список проблем в выводе). Каждый запуск пишется в health.log.
ИИ не используется, поэтому лимиты Claude на проверку не тратятся.
"""

import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import storage
from fetch_news import load_items, pick

HERE = Path(__file__).parent
LOG = HERE / "health.log"
CLAUDE = Path.home() / ".local" / "bin" / "claude.exe"
STYLE_DIR = Path(r"C:\Users\Anita\Desktop\Claude перенос\Для ChatGPT\02 Виральный контент\Сценарии видео")
SECRET_FILES = (".env", "news.db", "memory.md", ".memory-state", "health.log", "bot.log")
STUCK_AFTER = timedelta(hours=2)
# Windows: запустить бота отдельно от окна, которое его запустило, и без чёрного окна
DETACHED = 0x00000008 | 0x00000200 | 0x08000000


def read_env():
    values = {}
    for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def notify(text):
    env = read_env()
    data = urllib.parse.urlencode({"chat_id": env["TELEGRAM_OWNER_CHAT_ID"], "text": text}).encode()
    url = f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage"
    urllib.request.urlopen(url, data=data, timeout=30).read()


def powershell(command):
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip()


def bot_running():
    count = powershell(
        "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Where-Object { $_.CommandLine -match 'bot\\.py' }).Count")
    return count not in ("", "0")


def start_bot():
    log = open(HERE / "bot.log", "a", encoding="utf-8")
    subprocess.Popen(["py", "-u", "bot.py"], cwd=HERE, stdout=log, stderr=log,
                     creationflags=DETACHED, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    time.sleep(8)
    return bot_running()


# ---------- Проверки. Каждая возвращает список пар (вид, текст) ----------
# вид: fixed — починено само; alert — сообщить Ане, агент не нужен; agent — нужна помощь агента

def check_bot():
    if bot_running():
        return []
    if start_bot():
        return [("fixed", "Бот @scenariostech_bot был выключен — я запустил его заново.")]
    return [("agent", "Бот выключен, и перезапустить его не получилось (см. bot.log).")]


def check_tasks():
    found = []
    now = datetime.now()
    for status in ("queued", "running"):
        for task_id, _, text, received_at in storage.tasks_with_status(status):
            if now - datetime.strptime(received_at, "%Y-%m-%d %H:%M") > STUCK_AFTER:
                storage.set_task(task_id, "waiting")
                found.append(("fixed", f"Задача {task_id} «{text[:60]}» зависла — вернул её в ждущие, "
                             "повторить можно командой /run."))
    with storage.connect() as db:
        failed = db.execute("SELECT id, text, result FROM tasks WHERE status = 'failed'").fetchall()
        for task_id, text, result in failed:
            db.execute("UPDATE tasks SET status = 'failed-reported' WHERE id = ?", (task_id,))
            found.append(("alert", f"Задача {task_id} «{text[:60]}» не выполнилась: {str(result)[:150]}"))
    return found


def check_claude_login():
    try:
        output = subprocess.run([str(CLAUDE), "auth", "status"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60).stdout
        if json.loads(output).get("loggedIn"):
            return []
    except Exception:
        pass
    return [("alert", "⚠️ Claude Code на ноутбуке разлогинился: задачи из бота не будут выполняться. "
            "Нужен вход — напишите Claude в приложении «войди в Claude для бота».")]


def check_feed():
    try:
        items = list(load_items())
    except Exception as error:
        return [("agent", f"Лента TechCrunch не загружается: {error}")]
    if not items:
        return [("agent", "Лента TechCrunch пустая: в ней 0 материалов.")]
    if not pick(items, 72):
        return [("agent", f"В ленте {len(items)} материалов, но за 3 дня ни один не прошёл фильтр тем — "
                    "возможно, TechCrunch переименовал рубрики (TOPICS в fetch_news.py).")]
    return []


def check_style_dir():
    if STYLE_DIR.is_dir() and any(STYLE_DIR.glob("*.md")):
        return []
    return [("agent", f"Папка со стилем не найдена: {STYLE_DIR}")]


def check_secrets():
    tracked = subprocess.run(["git", "ls-files"], cwd=HERE, capture_output=True, text=True,
                             encoding="utf-8").stdout.split()
    leaked = [name for name in tracked if Path(name).name in SECRET_FILES]
    if leaked:
        return [("agent", f"СРОЧНО: в публичном git отслеживаются личные файлы: {', '.join(leaked)}")]
    return []


CHECKS = [check_bot, check_tasks, check_claude_login, check_feed, check_style_dir, check_secrets]


def main():
    if "--notify" in sys.argv:
        notify(" ".join(sys.argv[sys.argv.index("--notify") + 1:]))
        print("Сообщение отправлено.")
        return 0

    found = []
    for check in CHECKS:
        try:
            found += check()
        except Exception as error:
            found.append(("agent", f"Проверка {check.__name__} упала: {error}"))
    labels = {"fixed": "ПОЧИНЕНО", "alert": "ВНИМАНИЕ", "agent": "НУЖНА ПОМОЩЬ"}
    to_owner = [text for kind, text in found if kind in ("fixed", "alert")]
    for_agent = [text for kind, text in found if kind == "agent"]

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    status = "НУЖЕН АГЕНТ" if for_agent else "ЕСТЬ ОТЧЁТ" if to_owner else "OK"
    with LOG.open("a", encoding="utf-8") as log:
        log.write(f"[{stamp}] {status}" +
                  "".join(f"\n    {labels[kind]}: {text}" for kind, text in found) + "\n")

    # Владельцу пишем только когда что-то произошло; проблемы для агента он отправит сам после разбора
    if to_owner:
        notify("🔧 Проверка проекта " + stamp + ":\n\n" + "\n\n".join(to_owner))
    print(status)
    for kind, text in found:
        print(f"{labels[kind]}: {text}")
    return 2 if for_agent else 1 if to_owner else 0


if __name__ == "__main__":
    sys.exit(main())
