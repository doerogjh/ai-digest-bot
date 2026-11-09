import os
import sys
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
import httpx
from dotenv import load_dotenv

CURRENT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(CURRENT_DIR))

import database
from scraper import CATEGORIES, fetch_all_categories
from summarizer import summarize_repo

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_message(client: httpx.AsyncClient, text: str):
    """Отправляет сообщение в Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не заданы!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = await client.post(url, json=payload, timeout=20.0)
        if response.status_code == 200:
            logger.info("Сообщение успешно отправлено в Telegram!")
            return True
        else:
            logger.error("Ошибка Telegram API (%s): %s", response.status_code, response.text)
            # Попробуем без parse_mode на случай непредвиденных HTML тегов
            payload.pop("parse_mode", None)
            res2 = await client.post(url, json=payload, timeout=20.0)
            return res2.status_code == 200
    except Exception as e:
        logger.error("Исключение при отправке в Telegram: %s", e)
        return False

async def generate_and_send_daily_digest():
    """Сбор свежих данных, сохранение в архив памяти и отправка дайджеста в Telegram."""
    await database.init_db()
    today_str = database.get_current_date_str()
    logger.info("Запуск утреннего сбора дайджеста за %s...", today_str)

    # 1. Сканируем GitHub по всем 5 темам
    all_data = await fetch_all_categories()
    for cat_key, repos in all_data.items():
        if repos:
            await database.save_daily_snapshot(repos, cat_key, today_str)

    stats = await database.get_memory_stats()
    logger.info("Память сохранена: %s дней в архиве.", stats["days_count"])

    # 2. Формируем красивое сообщение для Telegram
    # Вступительный заголовок
    now = datetime.now(timezone.utc)
    header = (
        f"☕ <b>Доброе утро! Твой IT &amp; GitHub Дайджест</b>\n"
        f"📅 <i>{today_str}</i>\n"
        f"🧠 <i>В памяти ПК сохранено {stats['days_count']} дней ({stats['history_records']} записей)</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )

    category_blocks = []
    # Берём топ-3 самых ярких репозитория по каждой из 5 тем
    for cat_key, cat_info in CATEGORIES.items():
        repos = await database.get_repos_by_date_and_category(today_str, cat_key, limit=3)
        if not repos:
            continue

        block_lines = [f"<b>{cat_info['title']}</b>"]
        for idx, r in enumerate(repos, 1):
            name = r["repo_id"]
            stars = r.get("stars", "0")
            url = r.get("url", f"https://github.com/{name}")
            desc = r.get("description", "Без описания")
            if len(desc) > 90:
                desc = desc[:87] + "..."
            block_lines.append(f"{idx}. <a href=\"{url}\"><b>{name}</b></a> (⭐ <code>{stars}</code>)\n   └ <i>{desc}</i>")

        category_blocks.append("\n".join(block_lines))

    # Склеиваем сообщения так, чтобы уложиться в лимит Telegram (4096 символов)
    async with httpx.AsyncClient() as client:
        # Первое вводное сообщение с первыми 3 категориями
        part1 = header + "\n\n".join(category_blocks[:3])
        await send_telegram_message(client, part1)

        # Второе сообщение с остальными категориями
        if len(category_blocks) > 3:
            part2 = "\n\n".join(category_blocks[3:]) + (
                "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 <i>Все проекты сохранены в постоянный архив памяти.</i>"
            )
            await send_telegram_message(client, part2)

    logger.info("Дайджест успешно разослан!")

if __name__ == "__main__":
    asyncio.run(generate_and_send_daily_digest())
