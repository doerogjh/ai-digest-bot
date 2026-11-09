import os
import logging
import html
from typing import List, Dict, Any

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

import database
from scraper import CATEGORIES, fetch_category_repos, fetch_all_categories
from summarizer import summarize_repo

load_dotenv()
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAGE_SIZE = 5

def escape_html(text: str) -> str:
    """Безопасное экранирование спецсимволов HTML."""
    if not text:
        return ""
    return html.escape(str(text))

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура с 5 категориями и кнопками управления."""
    builder = InlineKeyboardBuilder()
    
    # 5 основных категорий
    for cat_key, cat_data in CATEGORIES.items():
        builder.button(text=cat_data["title"], callback_data=f"cat:{cat_key}:0")
    builder.adjust(1) # по одной кнопке в ряд для красоты и читаемости

    # Дополнительные кнопки
    builder.row(
        InlineKeyboardButton(text="🔄 Обновить GitHub", callback_data="refresh_all"),
        InlineKeyboardButton(text="⭐ Моя память", callback_data="favorites:0")
    )
    return builder.as_markup()

def category_page_keyboard(category_key: str, page: int, total_items: int, items_on_page: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Клавиатура для страницы категории со списком проектов."""
    builder = InlineKeyboardBuilder()

    # Кнопки с номерами для перехода в детальный вид
    num_buttons = []
    for idx, repo in enumerate(items_on_page):
        global_idx = page * PAGE_SIZE + idx + 1
        num_buttons.append(
            InlineKeyboardButton(text=f"№{global_idx}", callback_data=f"repo:{category_key}:{page}:{repo['repo_id']}")
        )
    if num_buttons:
        builder.row(*num_buttons)

    # Навигация (Вперед / Назад)
    nav_buttons = []
    total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE

    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{category_key}:{page - 1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page + 1}/{max(1, total_pages)}", callback_data="noop"))

    if (page + 1) * PAGE_SIZE < total_items:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"cat:{category_key}:{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    # Кнопка возврата в меню
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")
    )
    return builder.as_markup()

def repo_detail_keyboard(category_key: str, page: int, repo_id: str, is_fav: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура детального экрана репозитория."""
    builder = InlineKeyboardBuilder()
    
    fav_text = "❌ Удалить из памяти" if is_fav else "⭐ Сохранить в память"
    fav_action = f"fav_rm:{category_key}:{page}:{repo_id}" if is_fav else f"fav_add:{category_key}:{page}:{repo_id}"
    
    builder.row(
        InlineKeyboardButton(text=fav_text, callback_data=fav_action),
        InlineKeyboardButton(text="🔗 GitHub", url=f"https://github.com/{repo_id}")
    )
    builder.row(
        InlineKeyboardButton(text=f"🔙 Назад к списку (Стр. {page + 1})", callback_data=f"cat:{category_key}:{page}")
    )
    return builder.as_markup()

# Инициализация роутера
dp = Dispatcher()

@dp.message(Command("start", "digest", "help"))
async def cmd_start(message: Message):
    stats = await database.get_stats()
    text = (
        "👋 <b>Привет! Я твой персональный IT &amp; GitHub Дайджест-бот.</b>\n\n"
        "Я отслеживаю тренды, новинки и инструменты на GitHub, сортирую их по 5 ключевым направлениям и храню локальную память на твоем компьютере.\n\n"
        f"📊 <b>В памяти:</b> {stats['total_repos']} репозиториев\n\n"
        "Выбери тему, о которой хочешь почитать прямо сейчас:"
    )
    await message.answer(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(call: CallbackQuery):
    stats = await database.get_stats()
    text = (
        "📌 <b>Главное меню дайджеста</b>\n\n"
        f"📊 <b>В локальной памяти:</b> {stats['total_repos']} репозиториев\n\n"
        "Выбери категорию:"
    )
    await call.message.edit_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery):
    parts = call.data.split(":")
    cat_key = parts[1]
    page = int(parts[2])

    if cat_key not in CATEGORIES:
        await call.answer("Неизвестная категория", show_alert=True)
        return

    cat_title = CATEGORIES[cat_key]["title"]
    
    # Загружаем из базы данных
    repos = await database.get_repos_by_category(cat_key, limit=30)
    
    # Если в базе пусто — парсим GitHub прямо сейчас
    if not repos:
        await call.answer("⚡ Загружаю свежие проекты с GitHub...", show_alert=False)
        fresh_repos = await fetch_category_repos(cat_key, max_items=25)
        if fresh_repos:
            await database.save_repos(fresh_repos, cat_key)
            repos = await database.get_repos_by_category(cat_key, limit=30)

    total_items = len(repos)
    if total_items == 0:
        await call.message.edit_text(
            f"<b>{escape_html(cat_title)}</b>\n\nПока ничего не найдено. Нажми «Обновить GitHub».",
            reply_markup=main_menu_keyboard(),
            parse_mode="HTML"
        )
        await call.answer()
        return

    # Пагинация
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    page_items = repos[start_idx:end_idx]

    lines = [f"<b>{cat_title}</b> (всего в базе: {total_items})\n"]
    for idx, repo in enumerate(page_items):
        item_num = start_idx + idx + 1
        name = escape_html(repo["repo_id"])
        stars = escape_html(repo.get("stars", "0"))
        desc = escape_html(repo.get("description", "Без описания"))
        if len(desc) > 90:
            desc = desc[:87] + "..."
        lines.append(f"<b>№{item_num}</b> ⭐ <code>{stars}</code> | <b>{name}</b>\n   <i>{desc}</i>\n")

    lines.append("<i>Нажми на кнопку с номером проекта ниже, чтобы открыть подробный AI-разбор:</i>")
    text = "\n".join(lines)

    await call.message.edit_text(
        text,
        reply_markup=category_page_keyboard(cat_key, page, total_items, page_items),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await call.answer()

@dp.callback_query(F.data.startswith("repo:"))
async def cb_repo_detail(call: CallbackQuery):
    # repo:<category>:<page>:<repo_id>
    _, cat_key, page_str, repo_id = call.data.split(":", 3)
    page = int(page_str)

    repo = await database.get_repo_by_id(repo_id)
    if not repo:
        await call.answer("Проект не найден в памяти", show_alert=True)
        return

    await call.answer("🧠 Анализирую проект...", show_alert=False)
    
    # Получаем или генерируем AI-описание
    summary = await summarize_repo(repo)
    
    # Проверяем, в избранном ли
    favs = await database.get_favorites(call.from_user.id)
    is_fav = any(f["repo_id"] == repo_id for f in favs)

    reply_markup = repo_detail_keyboard(cat_key, page, repo_id, is_fav=is_fav)

    try:
        await call.message.edit_text(
            summary,
            reply_markup=reply_markup,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception:
        # Fallback без markdown форматирования на случай непредвиденных символов
        await call.message.edit_text(
            summary,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

@dp.callback_query(F.data.startswith("fav_add:"))
async def cb_fav_add(call: CallbackQuery):
    _, cat_key, page_str, repo_id = call.data.split(":", 3)
    await database.add_favorite(call.from_user.id, repo_id)
    await call.answer("⭐ Сохранено в локальную память!", show_alert=True)
    await call.message.edit_reply_markup(
        reply_markup=repo_detail_keyboard(cat_key, int(page_str), repo_id, is_fav=True)
    )

@dp.callback_query(F.data.startswith("fav_rm:"))
async def cb_fav_rm(call: CallbackQuery):
    _, cat_key, page_str, repo_id = call.data.split(":", 3)
    await database.remove_favorite(call.from_user.id, repo_id)
    await call.answer("Удалено из памяти", show_alert=True)
    await call.message.edit_reply_markup(
        reply_markup=repo_detail_keyboard(cat_key, int(page_str), repo_id, is_fav=False)
    )

@dp.callback_query(F.data.startswith("favorites:"))
async def cb_favorites(call: CallbackQuery):
    favs = await database.get_favorites(call.from_user.id)
    if not favs:
        await call.answer("В избранном пока ничего нет!", show_alert=True)
        return

    lines = [f"⭐ <b>Твоя сохранённая память</b> (проектов: {len(favs)})\n"]
    for idx, f in enumerate(favs[:15], 1):
        name = escape_html(f["repo_id"])
        stars = escape_html(f.get("stars", "0"))
        url = f.get("url", f"https://github.com/{f['repo_id']}")
        lines.append(f"{idx}. <a href=\"{url}\"><b>{name}</b></a> (⭐ {stars})")
    
    text = "\n".join(lines)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu"))
    
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
    await call.answer()

@dp.callback_query(F.data == "refresh_all")
async def cb_refresh_all(call: CallbackQuery):
    await call.answer("🔄 Начинаю сбор свежих репозиториев по всем 5 темам...", show_alert=False)
    total_saved = 0
    all_data = await fetch_all_categories()
    for cat_key, repos in all_data.items():
        if repos:
            cnt = await database.save_repos(repos, cat_key)
            total_saved += cnt
    
    stats = await database.get_stats()
    text = (
        f"✅ <b>Память обновлена!</b>\n\n"
        f"📥 Собрано и обновлено: <b>{total_saved}</b> репозиториев.\n"
        f"📊 Всего в локальной базе: <b>{stats['total_repos']}</b> проектов.\n\n"
        "Выбери тему для просмотра:"
    )
    await call.message.edit_text(text, reply_markup=main_menu_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()

async def run_bot():
    """Запуск long-polling бота."""
    if not TELEGRAM_BOT_TOKEN or "YOUR_TELEGRAM_BOT_TOKEN" in TELEGRAM_BOT_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не указан в файле .env!")
        print("Открой файл /home/defor/ai-digest-bot/.env и вставь туда свой токен от @BotFather.")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await database.init_db()
    
    # Первичный сбор данных, если база пустая
    stats = await database.get_stats()
    if stats["total_repos"] == 0:
        print("📦 Локальная база пустая. Собираем первую пачку репозиториев с GitHub...")
        all_data = await fetch_all_categories()
        for cat_key, repos in all_data.items():
            await database.save_repos(repos, cat_key)
        print("✅ Первичная память заполнена!")

    print("🚀 Telegram-бот успешно запущен и слушает команды!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())
