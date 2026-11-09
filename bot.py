import os
import logging
import html
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

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

def format_date_label(date_str: str) -> str:
    """Превращает YYYY-MM-DD в понятную метку (Сегодня, Вчера и т.д.)."""
    today_str = database.get_current_date_str()
    if date_str == today_str:
        return f"Сегодня ({date_str})"
    
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now(timezone.utc).date()
        delta = (today - d).days
        if delta == 1:
            return f"Вчера ({date_str})"
        elif delta == 7:
            return f"Неделю назад ({date_str})"
        elif 28 <= delta <= 31:
            return f"Месяц назад ({date_str})"
        elif 360 <= delta <= 370:
            return f"Год назад ({date_str})"
        else:
            return f"{date_str} ({delta} дн. назад)"
    except Exception:
        return date_str

def main_menu_keyboard(selected_date: Optional[str] = None) -> InlineKeyboardMarkup:
    """Главная клавиатура: 5 категорий + машина времени по датам."""
    if not selected_date:
        selected_date = database.get_current_date_str()

    builder = InlineKeyboardBuilder()

    # 5 основных категорий для выбранной даты
    for cat_key, cat_data in CATEGORIES.items():
        builder.button(text=cat_data["title"], callback_data=f"cat:{selected_date}:{cat_key}:0")
    builder.adjust(1)

    # Кнопки архива, машины времени и памяти
    builder.row(
        InlineKeyboardButton(text="⏳ Машина времени / Архив", callback_data=f"dates_menu:{selected_date}"),
        InlineKeyboardButton(text="⭐ Избранное", callback_data="favorites:0")
    )
    builder.row(
        InlineKeyboardButton(text="🔄 Сохранить срез сегодня", callback_data="save_today_snapshot")
    )
    return builder.as_markup()

def dates_picker_keyboard(current_selected_date: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора даты: Вчера, Месяц назад, Год назад или выбор из списка."""
    builder = InlineKeyboardBuilder()

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    year_ago = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    today_str = today.strftime("%Y-%m-%d")

    builder.row(
        InlineKeyboardButton(text="📌 Сегодня", callback_data=f"set_date:{today_str}"),
        InlineKeyboardButton(text="⏳ Вчера", callback_data=f"set_date:{yesterday}")
    )
    builder.row(
        InlineKeyboardButton(text="🗓️ Неделю назад", callback_data=f"set_date:{week_ago}"),
        InlineKeyboardButton(text="🗓️ Месяц назад", callback_data=f"set_date:{month_ago}")
    )
    builder.row(
        InlineKeyboardButton(text="📜 Год назад", callback_data=f"set_date:{year_ago}"),
        InlineKeyboardButton(text="🗂️ Все даты в памяти", callback_data="all_dates:0")
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Назад в меню", callback_data=f"main_menu:{current_selected_date}")
    )
    return builder.as_markup()

def category_page_keyboard(date_str: str, category_key: str, page: int, total_items: int, items_on_page: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Клавиатура для страницы категории со списком проектов за конкретную дату."""
    builder = InlineKeyboardBuilder()

    # Кнопки с номерами для перехода в детальный вид
    num_buttons = []
    for idx, repo in enumerate(items_on_page):
        global_idx = page * PAGE_SIZE + idx + 1
        num_buttons.append(
            InlineKeyboardButton(text=f"№{global_idx}", callback_data=f"repo:{date_str}:{category_key}:{page}:{repo['repo_id']}")
        )
    if num_buttons:
        builder.row(*num_buttons)

    # Навигация (Вперед / Назад)
    nav_buttons = []
    total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE

    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{date_str}:{category_key}:{page - 1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {page + 1}/{max(1, total_pages)}", callback_data="noop"))

    if (page + 1) * PAGE_SIZE < total_items:
        nav_buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"cat:{date_str}:{category_key}:{page + 1}"))

    if nav_buttons:
        builder.row(*nav_buttons)

    # Кнопки возврата
    builder.row(
        InlineKeyboardButton(text="⏳ Сменить дату", callback_data=f"dates_menu:{date_str}"),
        InlineKeyboardButton(text="🔙 Главное меню", callback_data=f"main_menu:{date_str}")
    )
    return builder.as_markup()

def repo_detail_keyboard(date_str: str, category_key: str, page: int, repo_id: str, is_fav: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура детального экрана репозитория."""
    builder = InlineKeyboardBuilder()
    
    fav_text = "❌ Удалить из избранного" if is_fav else "⭐ В избранное"
    fav_action = f"fav_rm:{date_str}:{category_key}:{page}:{repo_id}" if is_fav else f"fav_add:{date_str}:{category_key}:{page}:{repo_id}"
    
    builder.row(
        InlineKeyboardButton(text=fav_text, callback_data=fav_action),
        InlineKeyboardButton(text="🔗 GitHub", url=f"https://github.com/{repo_id}")
    )
    builder.row(
        InlineKeyboardButton(text=f"🔙 К списку (Стр. {page + 1})", callback_data=f"cat:{date_str}:{category_key}:{page}")
    )
    return builder.as_markup()

dp = Dispatcher()

@dp.message(Command("start", "digest", "help"))
async def cmd_start(message: Message):
    stats = await database.get_memory_stats()
    today_str = database.get_current_date_str()
    text = (
        "👋 <b>Привет! Я твой персональный IT &amp; GitHub Дайджест-бот с машиной времени.</b>\n\n"
        "Я не просто собираю новости, а <b>сохраняю постоянный архив</b> на твоем компьютере: "
        "ты всегда можешь посмотреть, что было вчера, месяц назад или год назад!\n\n"
        f"📅 <b>Текущая дата:</b> {format_date_label(today_str)}\n"
        f"🧠 <b>Архив памяти:</b> {stats['days_count']} сохранённых дней ({stats['history_records']} записей в архиве)\n\n"
        "Выбери тему или открой архив за прошлые дни:"
    )
    await message.answer(text, reply_markup=main_menu_keyboard(today_str), parse_mode="HTML")

@dp.callback_query(F.data.startswith("main_menu"))
async def cb_main_menu(call: CallbackQuery):
    parts = call.data.split(":")
    selected_date = parts[1] if len(parts) > 1 else database.get_current_date_str()
    stats = await database.get_memory_stats()

    text = (
        f"📌 <b>Главное меню дайджеста</b>\n\n"
        f"📅 <b>Выбранная дата:</b> <code>{format_date_label(selected_date)}</code>\n"
        f"🧠 <b>Дней в архиве памяти:</b> {stats['days_count']} (уникальных проектов: {stats['unique_repos']})\n\n"
        "Выбери тему для просмотра архива или нажми «Машина времени», чтобы посмотреть вчера/месяц назад:"
    )
    await call.message.edit_text(text, reply_markup=main_menu_keyboard(selected_date), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("dates_menu:"))
async def cb_dates_menu(call: CallbackQuery):
    selected_date = call.data.split(":")[1]
    stats = await database.get_memory_stats()
    text = (
        "⏳ <b>Машина времени: архив дайджестов</b>\n\n"
        "Здесь хранятся все когда-либо сохранённые подборки по дням. Выбери период, который хочешь просмотреть:\n\n"
        f"• Сейчас активна дата: <b>{format_date_label(selected_date)}</b>\n"
        f"• Всего сохранено дней: <b>{stats['days_count']}</b>"
    )
    await call.message.edit_text(text, reply_markup=dates_picker_keyboard(selected_date), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("set_date:"))
async def cb_set_date(call: CallbackQuery):
    new_date = call.data.split(":")[1]
    await call.answer(f"Выбрана дата: {new_date}")
    # Переходим в главное меню для этой даты
    stats = await database.get_memory_stats()
    text = (
        f"⏳ <b>Архив за дату:</b> <code>{format_date_label(new_date)}</code>\n\n"
        f"Вся память загружена. Выбери интересующую тему за этот день:"
    )
    await call.message.edit_text(text, reply_markup=main_menu_keyboard(new_date), parse_mode="HTML")

@dp.callback_query(F.data.startswith("all_dates:"))
async def cb_all_dates(call: CallbackQuery):
    dates = await database.get_history_dates()
    if not dates:
        await call.answer("Архив пуст!", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for d in dates[:15]:
        builder.button(text=f"📅 {format_date_label(d)}", callback_data=f"set_date:{d}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Назад к машине времени", callback_data=f"dates_menu:{dates[0]}"))

    text = "🗂️ <b>Все сохранённые срезы в памяти ПК:</b>\n\nВыбери любой день из списка:"
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("cat:"))
async def cb_category(call: CallbackQuery):
    # cat:<date_str>:<cat_key>:<page>
    parts = call.data.split(":")
    date_str = parts[1]
    cat_key = parts[2]
    page = int(parts[3])

    if cat_key not in CATEGORIES:
        await call.answer("Неизвестная категория", show_alert=True)
        return

    cat_title = CATEGORIES[cat_key]["title"]
    
    # Загружаем из архива за эту конкретную дату
    repos = await database.get_repos_by_date_and_category(date_str, cat_key, limit=30)
    
    # Если за эту дату в базе нет и дата — это сегодня, парсим GitHub
    today_str = database.get_current_date_str()
    if not repos and date_str == today_str:
        await call.answer("⚡ Сохраняю сегодняшний срез с GitHub...", show_alert=False)
        fresh_repos = await fetch_category_repos(cat_key, max_items=25)
        if fresh_repos:
            await database.save_daily_snapshot(fresh_repos, cat_key, today_str)
            repos = await database.get_repos_by_date_and_category(date_str, cat_key, limit=30)

    total_items = len(repos)
    if total_items == 0:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="⏳ Выбрать другую дату", callback_data=f"dates_menu:{date_str}"))
        builder.row(InlineKeyboardButton(text="🔙 Главное меню", callback_data=f"main_menu:{date_str}"))
        await call.message.edit_text(
            f"<b>{escape_html(cat_title)}</b>\n\nЗа дату <code>{date_str}</code> записей не найдено.",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await call.answer()
        return

    # Пагинация
    start_idx = page * PAGE_SIZE
    end_idx = start_idx + PAGE_SIZE
    page_items = repos[start_idx:end_idx]

    lines = [
        f"<b>{cat_title}</b>",
        f"📅 Срез за: <code>{format_date_label(date_str)}</code> (в архиве дня: {total_items} тем)\n"
    ]
    for idx, repo in enumerate(page_items):
        item_num = start_idx + idx + 1
        name = escape_html(repo["repo_id"])
        stars = escape_html(repo.get("stars", "0"))
        desc = escape_html(repo.get("description", "Без описания"))
        if len(desc) > 90:
            desc = desc[:87] + "..."
        lines.append(f"<b>№{item_num}</b> ⭐ <code>{stars}</code> | <b>{name}</b>\n   <i>{desc}</i>\n")

    lines.append("<i>Нажми на номер проекта ниже для полного AI-разбора:</i>")
    text = "\n".join(lines)

    await call.message.edit_text(
        text,
        reply_markup=category_page_keyboard(date_str, cat_key, page, total_items, page_items),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await call.answer()

@dp.callback_query(F.data.startswith("repo:"))
async def cb_repo_detail(call: CallbackQuery):
    # repo:<date_str>:<category>:<page>:<repo_id>
    _, date_str, cat_key, page_str, repo_id = call.data.split(":", 4)
    page = int(page_str)

    repo = await database.get_repo_by_id(repo_id, snapshot_date=date_str)
    if not repo:
        await call.answer("Проект не найден в архиве", show_alert=True)
        return

    await call.answer("🧠 Извлекаю карточку проекта из памяти...", show_alert=False)
    summary = await summarize_repo(repo)
    
    # Добавляем пометку даты среза
    date_header = f"🗓️ _Запись из архива памяти за {format_date_label(date_str)}_\n\n"
    full_text = date_header + summary

    favs = await database.get_favorites(call.from_user.id)
    is_fav = any(f["repo_id"] == repo_id for f in favs)

    reply_markup = repo_detail_keyboard(date_str, cat_key, page, repo_id, is_fav=is_fav)

    try:
        await call.message.edit_text(
            full_text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception:
        await call.message.edit_text(
            full_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )

@dp.callback_query(F.data.startswith("fav_add:"))
async def cb_fav_add(call: CallbackQuery):
    _, date_str, cat_key, page_str, repo_id = call.data.split(":", 4)
    await database.add_favorite(call.from_user.id, repo_id)
    await call.answer("⭐ Сохранено в Избранное!", show_alert=True)
    await call.message.edit_reply_markup(
        reply_markup=repo_detail_keyboard(date_str, cat_key, int(page_str), repo_id, is_fav=True)
    )

@dp.callback_query(F.data.startswith("fav_rm:"))
async def cb_fav_rm(call: CallbackQuery):
    _, date_str, cat_key, page_str, repo_id = call.data.split(":", 4)
    await database.remove_favorite(call.from_user.id, repo_id)
    await call.answer("Удалено из избранного", show_alert=True)
    await call.message.edit_reply_markup(
        reply_markup=repo_detail_keyboard(date_str, cat_key, int(page_str), repo_id, is_fav=False)
    )

@dp.callback_query(F.data.startswith("favorites:"))
async def cb_favorites(call: CallbackQuery):
    favs = await database.get_favorites(call.from_user.id)
    if not favs:
        await call.answer("В избранном пока ничего нет!", show_alert=True)
        return

    lines = [f"⭐ <b>Твоё избранное из архива</b> (сохранено: {len(favs)})\n"]
    for idx, f in enumerate(favs[:15], 1):
        name = escape_html(f["repo_id"])
        stars = escape_html(f.get("stars", "0"))
        url = f.get("url", f"https://github.com/{f['repo_id']}")
        lines.append(f"{idx}. <a href=\"{url}\"><b>{name}</b></a> (⭐ {stars})")
    
    text = "\n".join(lines)
    today_str = database.get_current_date_str()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Главное меню", callback_data=f"main_menu:{today_str}"))
    
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
    await call.answer()

@dp.callback_query(F.data == "save_today_snapshot")
async def cb_save_today_snapshot(call: CallbackQuery):
    await call.answer("🔄 Сканирую GitHub и архивирую сегодняшний срез...", show_alert=False)
    all_data = await fetch_all_categories()
    today_str = database.get_current_date_str()
    total_saved = 0
    for cat_key, repos in all_data.items():
        if repos:
            cnt = await database.save_daily_snapshot(repos, cat_key, today_str)
            total_saved += cnt
    
    stats = await database.get_memory_stats()
    text = (
        f"✅ <b>Архив памяти обновлён на дату {today_str}!</b>\n\n"
        f"📥 Сохранено в архив: <b>{total_saved}</b> записей.\n"
        f"🧠 Всего в памяти: <b>{stats['days_count']}</b> дней архива ({stats['history_records']} записей).\n\n"
        "Выбери тему для просмотра:"
    )
    await call.message.edit_text(text, reply_markup=main_menu_keyboard(today_str), parse_mode="HTML")

@dp.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery):
    await call.answer()

async def run_bot():
    """Запуск бота."""
    if not TELEGRAM_BOT_TOKEN or "YOUR_TELEGRAM_BOT_TOKEN" in TELEGRAM_BOT_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не указан в файле .env!")
        print("Открой файл /home/defor/ai-digest-bot/.env и вставь туда свой токен от @BotFather.")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    await database.init_db()
    
    stats = await database.get_memory_stats()
    print(f"🧠 Память загружена: {stats['days_count']} дней в архиве, {stats['history_records']} записей.")
    print("🚀 Telegram-бот запущен и слушает команды /start и /digest!")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())
