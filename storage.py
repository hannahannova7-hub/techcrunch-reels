"""Хранилище бота: база SQLite в файле news.db рядом с программой.

Запоминает, какие новости бот уже присылал, чтобы данные переживали перезапуск.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name("news.db")


def connect():
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """CREATE TABLE IF NOT EXISTS sent_news (
            link TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            published TEXT NOT NULL,
            first_sent_at TEXT NOT NULL,
            times_sent INTEGER NOT NULL DEFAULT 1
        )"""
    )
    return db


def remember(items):
    """Сохраняет присланные новости. Возвращает ссылки, которых раньше в базе не было."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    new_links = set()
    with connect() as db:
        for item in items:
            known = db.execute("SELECT 1 FROM sent_news WHERE link = ?", (item["link"],)).fetchone()
            if known:
                db.execute("UPDATE sent_news SET times_sent = times_sent + 1 WHERE link = ?",
                           (item["link"],))
            else:
                new_links.add(item["link"])
                db.execute(
                    "INSERT INTO sent_news (link, title, published, first_sent_at) VALUES (?, ?, ?, ?)",
                    (item["link"], item["title"],
                     item["published"].astimezone().strftime("%Y-%m-%d %H:%M"), now),
                )
    return new_links


def history(limit=10):
    """Последние новости из базы и общее количество записей."""
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM sent_news").fetchone()[0]
        rows = db.execute(
            "SELECT title, link, first_sent_at FROM sent_news "
            "ORDER BY first_sent_at DESC, published DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return total, rows
