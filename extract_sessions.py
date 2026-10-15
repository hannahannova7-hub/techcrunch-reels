"""Достаёт из записей сессий Claude Code новые реплики для обновления memory.md.

    py extract_sessions.py            печатает реплики после последней обработанной отметки
    py extract_sessions.py --done     сохраняет отметку: всё напечатанное учтено в памяти

Отметка лежит в .memory-state (не публикуется). Без неё берётся последний час.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / ".memory-state"
PENDING = HERE / ".memory-pending"
PROJECTS = Path.home() / ".claude" / "projects"
# Реплики самого задания по обновлению памяти в память не попадают.
TASK_MARKER = "MEMORY-UPDATE-TASK"
MAX_CHARS = 800


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def text_of(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = [p.get("text", "") for p in content or [] if isinstance(p, dict) and p.get("type") == "text"]
    return "\n".join(parts)


def session_lines(path, since):
    lines = []
    for raw in path.open(encoding="utf-8"):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("type") not in ("user", "assistant") or "timestamp" not in entry:
            continue
        text = text_of(entry.get("message", {})).strip()
        if TASK_MARKER in text:
            return []
        if text and parse_time(entry["timestamp"]) > since:
            stamp = parse_time(entry["timestamp"]).astimezone().strftime("%Y-%m-%d %H:%M")
            who = "Аня" if entry["type"] == "user" else "Claude"
            lines.append(f"[{stamp}] {who}: {text[:MAX_CHARS]}")
    return lines


def main():
    if "--done" in sys.argv:
        if PENDING.exists():
            PENDING.replace(STATE)
        print("Отметка сохранена.")
        return

    now = datetime.now(timezone.utc)
    since = parse_time(STATE.read_text().strip()) if STATE.exists() else now - timedelta(hours=1)
    PENDING.write_text(now.isoformat())

    found = 0
    for folder in PROJECTS.glob("*scenarios*"):
        for path in folder.glob("*.jsonl"):
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) <= since:
                continue
            lines = session_lines(path, since)
            if lines:
                found += len(lines)
                print(f"=== Сессия {path.stem} ===")
                print("\n".join(lines))
    if not found:
        print(f"Новых реплик после {since.astimezone():%Y-%m-%d %H:%M} нет.")


if __name__ == "__main__":
    main()
