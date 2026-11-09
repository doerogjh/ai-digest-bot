import aiosqlite
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any

DB_PATH = Path(__file__).parent / "memory.db"
logger = logging.getLogger(__name__)

async def init_db():
    """Инициализация базы данных и таблиц памяти."""
    async with aiosqlite.connect(DB_PATH) as db:
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_favorites (
                user_id INTEGER NOT NULL,
                repo_id TEXT NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY (user_id, repo_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_views (
                user_id INTEGER NOT NULL,
                repo_id TEXT NOT NULL,
                viewed_at TEXT NOT NULL,
                PRIMARY KEY (user_id, repo_id)
            )
        """)
        await db.commit()
    logger.info("База данных памяти успешно инициализирована: %s", DB_PATH)

async def save_repos(repos: List[Dict[str, Any]], category: str) -> int:
    """Сохраняет найденные репозитории в память, обновляет дату последнего обнаружения."""
    now = datetime.now(timezone.utc).isoformat()
    saved_count = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for r in repos:
            repo_id = r["repo_id"]
            name = r.get("name", repo_id)
            url = r.get("url", f"https://github.com/{repo_id}")
            stars = r.get("stars", "0")
            description = r.get("description", "")
            tags = json.dumps(r.get("tags", []), ensure_ascii=False)
            ai_summary = r.get("ai_summary")

            await db.execute("""
                INSERT INTO repos (repo_id, category, name, url, stars, description, tags, ai_summary, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo_id) DO UPDATE SET
                    stars = excluded.stars,
                    description = CASE WHEN excluded.description != '' THEN excluded.description ELSE repos.description END,
                    tags = excluded.tags,
                    last_seen = excluded.last_seen
            """, (repo_id, category, name, url, stars, description, tags, ai_summary, now, now))
            saved_count += 1
        await db.commit()
    return saved_count

async def get_repos_by_category(category: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Получает последние репозитории по категории."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM repos
            WHERE category = ?
            ORDER BY last_seen DESC, stars DESC
            LIMIT ?
        """, (category, limit)) as cursor:
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

async def get_repo_by_id(repo_id: str) -> Optional[Dict[str, Any]]:
    """Получает данные репозитория по ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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

async def update_ai_summary(repo_id: str, summary: str):
    """Сохраняет AI-выжимку в память репозитория."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE repos SET ai_summary = ? WHERE repo_id = ?", (summary, repo_id))
        await db.commit()

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

async def get_stats() -> Dict[str, Any]:
    """Возвращает общую статистику памяти бота."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*), COUNT(DISTINCT category) FROM repos") as cur:
            row = await cur.fetchone()
            total_repos = row[0] if row else 0
            categories_count = row[1] if row else 0
        return {"total_repos": total_repos, "categories_count": categories_count}
