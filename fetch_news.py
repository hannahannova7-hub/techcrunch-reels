"""Собирает свежие новости TechCrunch по темам блога и сохраняет их в candidates.md.

Запуск: python fetch_news.py [часов]   (по умолчанию 24, если пусто — расширяем до 72)
Нужен только Python, дополнительные пакеты не требуются.
"""

import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FEED_URL = "https://techcrunch.com/feed/"
OUTPUT = Path(__file__).with_name("candidates.md")

# Рубрики TechCrunch, которые подходят под темы блога: ИИ, IT, технологии, стартапы, финтех, венчур.
TOPICS = {
    "ai", "apps", "startups", "fintech", "venture", "fundraising", "security",
    "enterprise", "robotics", "hardware", "gadgets", "crypto", "media & entertainment",
}
# Служебные материалы и рубрики, которые не берём (политика, реклама билетов на конференцию).
SKIP_TITLE_WORDS = ("ticket", "save 50%", "save up to", "early booking", "techcrunch disrupt 2026: day")
SKIP_CATEGORIES = {"government & policy", "policy", "politics", "elections"}


def load_items():
    request = urllib.request.Request(FEED_URL, headers={"User-Agent": "techcrunch-reels/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())
    for item in root.iter("item"):
        categories = [c.text.strip() for c in item.findall("category") if c.text]
        yield {
            "title": item.findtext("title", "").strip(),
            "link": item.findtext("link", "").strip(),
            "published": parsedate_to_datetime(item.findtext("pubDate")),
            "categories": categories,
        }


def is_relevant(item):
    lowered = {c.lower() for c in item["categories"]}
    if lowered & SKIP_CATEGORIES:
        return False
    if any(word in item["title"].lower() for word in SKIP_TITLE_WORDS):
        return False
    return bool(lowered & TOPICS)


def pick(items, hours):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return [i for i in items if i["published"] >= since and is_relevant(i)]


def main():
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    items = list(load_items())
    chosen = pick(items, hours)
    if not chosen and hours < 72:
        hours = 72
        chosen = pick(items, hours)

    lines = [
        f"# Кандидаты TechCrunch за последние {hours} ч",
        "",
        f"Собрано: {datetime.now().strftime('%Y-%m-%d %H:%M')}. "
        "Дата ниже — дата публикации на TechCrunch, дату самого события проверяем отдельно.",
        "",
    ]
    for item in chosen:
        date = item["published"].astimezone().strftime("%Y-%m-%d %H:%M")
        lines.append(f"- **{item['title']}** — {date}  ")
        lines.append(f"  {item['link']}  ")
        lines.append(f"  Рубрики: {', '.join(item['categories'])}")
    if not chosen:
        lines.append("Подходящих материалов за последние трое суток нет.")

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Найдено {len(chosen)} кандидатов, список сохранён в {OUTPUT.name}")


if __name__ == "__main__":
    main()
