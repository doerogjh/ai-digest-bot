import os
import logging
from typing import Dict, Any
from dotenv import load_dotenv
from database import update_ai_summary

load_dotenv()
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

async def summarize_repo(repo: Dict[str, Any]) -> str:
    """Генерирует краткую выжимку о репозитории с помощью Gemini или аккуратный fallback."""
    # Если в базе уже есть готовое описание
    if repo.get("ai_summary"):
        return repo["ai_summary"]

    name = repo.get("repo_id", "Unknown")
    desc = repo.get("description", "Без описания")
    stars = repo.get("stars", "0")
    tags = ", ".join(repo.get("tags", [])) or "нет тегов"
    url = repo.get("url", f"https://github.com/{name}")

    if not GEMINI_API_KEY:
        # Умный fallback без ключа
        summary = (
            f"📌 **{name}** (⭐ {stars})\n\n"
            f"📖 **Описание:** {desc or 'Описание отсутствует'}\n"
            f"🏷️ **Теги:** `{tags}`\n"
            f"🔗 [Открыть репозиторий на GitHub]({url})\n\n"
            f"💡 *Совет: добавь GEMINI_API_KEY в .env для автоматической генерации AI-обзоров.*"
        )
        return summary

    try:
        from google import genai

        client = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            f"Ты технический редактор и эксперт. Сделай краткий, сочный разбор репозитория с GitHub на русском языке.\n"
            f"Название: {name}\n"
            f"Звезды: {stars}\n"
            f"Теги: {tags}\n"
            f"Исходное описание: {desc}\n\n"
            f"Требования к ответу:\n"
            f"1. Эмодзи и название проекта жирным.\n"
            f"2. ⚡ Суть: в 1-2 предложениях простыми словами, что это делает.\n"
            f"3. 🛠️ Ключевые фичи / применение: 2-3 коротких пункта.\n"
            f"4. 🎯 Кому пригодится: 1 предложение.\n"
            f"5. Никакой воды и рекламы."
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        ai_text = response.text.strip()
        formatted_summary = (
            f"{ai_text}\n\n"
            f"⭐ **Звезд:** {stars} | 🏷️ **Теги:** `{tags}`\n"
            f"🔗 [Перейти на GitHub]({url})"
        )

        # Сохраняем в память
        await update_ai_summary(repo["repo_id"], formatted_summary)
        return formatted_summary

    except Exception as e:
        logger.error("Ошибка при обращении к Gemini API: %s", e)
        return (
            f"📌 **{name}** (⭐ {stars})\n\n"
            f"📖 **Описание:** {desc}\n"
            f"🏷️ **Теги:** `{tags}`\n"
            f"🔗 [Открыть на GitHub]({url})"
        )
