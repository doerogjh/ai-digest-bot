import aiosqlite
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any

import os
_DATA_DIR = Path(os.getenv("DATA_DIR", str(Path(__file__).parent)))
_DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = _DATA_DIR / "memory.db"
logger = logging.getLogger(__name__)

def get_current_date_str() -> str:
    """Возвращает текущую дату в формате YYYY-MM-DD."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

async def init_db():
    """Инициализация базы данных: постоянный архив по дням + избранное."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Постоянный архив дайджестов по датам (день за днем навсегда)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS digest_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL, -- Формат: YYYY-MM-DD
                category TEXT NOT NULL,
                repo_id TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                stars TEXT,
                description TEXT,
                tags TEXT,
                ai_summary TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(snapshot_date, category, repo_id)
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_history_date ON digest_history(snapshot_date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_history_date_cat ON digest_history(snapshot_date, category)")

        # Общая таблица репозиториев (глобальная память)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS repos (
                repo_id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                stars TEXT,
                description TEXT,
                tags TEXT,
                ai_summary TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )
        """)

        # Избранное пользователя
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_favorites (
                user_id INTEGER NOT NULL,
                repo_id TEXT NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (user_id, repo_id)
            )
        """)
        await db.commit()
    logger.info("База данных архива памяти инициализирована: %s", DB_PATH)

async def save_daily_snapshot(repos: List[Dict[str, Any]], category: str, snapshot_date: Optional[str] = None) -> int:
    """
    Сохраняет слепок дня в архив памяти навсегда.
    Если запись за этот день и категорию уже есть, не затирает её, а сохраняет историю.
    """
    if not snapshot_date:
        snapshot_date = get_current_date_str()

    now_iso = datetime.now(timezone.utc).isoformat()
    saved = 0

    async with aiosqlite.connect(DB_PATH) as db:
        for r in repos:
            repo_id = r["repo_id"]
            name = r.get("name", repo_id)
            url = r.get("url", f"https://github.com/{repo_id}")
            stars = r.get("stars", "0")
            description = r.get("description", "")
            tags = json.dumps(r.get("tags", []), ensure_ascii=False)
            ai_summary = r.get("ai_summary")

            # 1. Сохраняем в архив конкретного дня (snapshot_date)
            await db.execute("""
                INSERT OR IGNORE INTO digest_history 
                (snapshot_date, category, repo_id, name, url, stars, description, tags, ai_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (snapshot_date, category, repo_id, name, url, stars, description, tags, ai_summary, now_iso))

            # 2. Также поддерживаем общий реестр всех виденных репозиториев
            await db.execute("""
                INSERT INTO repos (repo_id, category, name, url, stars, description, tags, ai_summary, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_id) DO UPDATE SET
                    stars = excluded.stars,
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE repos.description END,
                    tags = excluded.tags,
                    last_seen = excluded.last_seen
            """, (repo_id, category, name, url, stars, description, tags, ai_summary, snapshot_date, now_iso))
            saved += 1

        await db.commit()
    return saved

async def get_history_dates() -> List[str]:
    """Возвращает список всех доступных дат в архиве памяти от новых к старым."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT DISTINCT snapshot_date 
            FROM digest_history 
            ORDER BY snapshot_date DESC
        """) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def get_repos_by_date_and_category(snapshot_date: str, category: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Получает репозитории из архива за конкретную дату и категорию."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM digest_history
            WHERE snapshot_date = ? AND category = ?
            ORDER BY id ASC
            LIMIT ?
        """, (snapshot_date, category, limit)) as cursor:
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["tags"] = json.loads(item["tags"]) if item["tags"] else []
                except Exception:
                    item["tags"] = []
                result.append(item)
            return result

async def get_repo_by_id(repo_id: str, snapshot_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Получает информацию о репозитории (из архива конкретной даты или общей базы)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if snapshot_date:
            async with db.execute(
                "SELECT * FROM digest_history WHERE repo_id = ? AND snapshot_date = ? LIMIT 1",
                (repo_id, snapshot_date)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    item = dict(row)
                    try:
                        item["tags"] = json.loads(item["tags"]) if item["tags"] else []
                    except Exception:
                        item["tags"] = []
                    return item

        # Иначе из общей базы
        async with db.execute("SELECT * FROM repos WHERE repo_id = ?", (repo_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["tags"] = json.loads(item["tags"]) if item["tags"] else []
            except Exception:
                item["tags"] = []
            return item

async def update_ai_summary(repo_id: str, summary: str, snapshot_date: Optional[str] = None):
    """Обновляет AI-выжимку в памяти (и в глобальной таблице, и в архиве даты)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE repos SET ai_summary = ? WHERE repo_id = ?", (summary, repo_id))
        if snapshot_date:
            await db.execute(
                "UPDATE digest_history SET ai_summary = ? WHERE repo_id = ? AND snapshot_date = ?",
                (summary, repo_id, snapshot_date)
            )
        else:
            await db.execute("UPDATE digest_history SET ai_summary = ? WHERE repo_id = ?", (summary, repo_id))
        await db.commit()

async def search_memory(query: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Полнотекстовый поиск по всей сохраненной за всё время истории памяти."""
    search_pattern = f"%{query}%"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT DISTINCT repo_id, name, category, url, stars, description, snapshot_date
            FROM digest_history
            WHERE name LIKE ? OR description LIKE ? OR tags LIKE ?
            ORDER BY snapshot_date DESC
            LIMIT ?
        """, (search_pattern, search_pattern, search_pattern, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def add_favorite(user_id: int, repo_id: str):
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO user_favorites (user_id, repo_id, added_at)
            VALUES (?, ?, ?)
        """, (user_id, repo_id, now))
        await db.commit()

async def remove_favorite(user_id: int, repo_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_favorites WHERE user_id = ? AND repo_id = ?", (user_id, repo_id))
        await db.commit()

async def get_favorites(user_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT r.*, f.added_at
            FROM user_favorites f
            JOIN repos r ON f.repo_id = r.repo_id
            WHERE f.user_id = ?
            ORDER BY f.added_at DESC
        """, (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

async def get_memory_stats() -> Dict[str, Any]:
    """Возвращает расширенную статистику архива памяти: дни, общее число записей."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(DISTINCT snapshot_date), COUNT(*) FROM digest_history") as cur:
            row = await cur.fetchone()
            days_count = row[0] if row else 0
            total_history_records = row[1] if row else 0

        async with db.execute("SELECT COUNT(*) FROM repos") as cur:
            row2 = await cur.fetchone()
            unique_repos = row2[0] if row2 else 0

        return {
            "days_count": days_count,
            "history_records": total_history_records,
            "unique_repos": unique_repos
        }
