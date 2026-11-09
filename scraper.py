import asyncio
import logging
from typing import List, Dict, Any
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CATEGORIES = {
    "ai": {
        "title": "🤖 ИИ, Боты & Нейросети",
        "topics": ["artificial-intelligence", "llm", "ai-agents", "machine-learning"]
    },
    "hacking": {
        "title": "🛡️ Хакинг & Безопасность",
        "topics": ["security", "hacking", "pentest", "exploit"]
    },
    "dev": {
        "title": "💻 Программирование & DevTools",
        "topics": ["developer-tools", "programming", "frameworks", "compilers"]
    },
    "devops": {
        "title": "🚀 DevOps & Сисадмин",
        "topics": ["devops", "sysadmin", "kubernetes", "docker", "monitoring"]
    },
    "tools": {
        "title": "🛠️ Необычные & Полезные тулзы",
        "topics": ["awesome", "cli", "terminal", "productivity", "utilities"]
    }
}

async def fetch_topic_repos(client: httpx.AsyncClient, topic: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Парсит репозитории со страницы топика GitHub без ограничений API."""
    url = f"https://github.com/topics/{topic}"
    repos = []
    try:
        response = await client.get(url, headers=HEADERS, timeout=12.0)
        if response.status_code != 200:
            logger.warning("Ошибка при получении топика %s: HTTP %s", topic, response.status_code)
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("article")

        for art in articles[:limit]:
            h3 = art.find("h3")
            if not h3:
                continue

            links = h3.find_all("a")
            if not links:
                continue

            repo_path = links[-1].get("href", "").strip("/")
            if not repo_path or "/" not in repo_path:
                continue

            # Описание
            p_desc = art.find("p")
            desc = p_desc.text.strip() if p_desc else ""

            # Количество звезд
            star_span = art.find("span", id=lambda x: x and x.startswith("repo-stars-counter"))
            stars = star_span.text.strip() if star_span else "N/A"

            # Теги / темы
            tag_elements = art.find_all("a", class_=lambda c: c and "topic-tag" in c)
            tags = [t.text.strip() for t in tag_elements if t.text.strip()][:5]

            repos.append({
                "repo_id": repo_path,
                "name": repo_path.split("/")[-1],
                "url": f"https://github.com/{repo_path}",
                "description": desc,
                "stars": stars,
                "tags": tags,
                "topic": topic
            })
    except Exception as e:
        logger.error("Исключение при парсинге топика %s: %s", topic, e)

    return repos

async def fetch_category_repos(category_key: str, max_items: int = 25) -> List[Dict[str, Any]]:
    """Сбор и дедупликация репозиториев для указанной категории (до 20-25 штук)."""
    if category_key not in CATEGORIES:
        return []

    cat_info = CATEGORIES[category_key]
    topics = cat_info["topics"]
    seen_ids = set()
    combined_repos = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [fetch_topic_repos(client, t, limit=12) for t in topics]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list):
                for repo in res:
                    rid = repo["repo_id"]
                    if rid not in seen_ids:
                        seen_ids.add(rid)
                        combined_repos.append(repo)
                        if len(combined_repos) >= max_items:
                            break
            if len(combined_repos) >= max_items:
                break

    return combined_repos

async def fetch_all_categories() -> Dict[str, List[Dict[str, Any]]]:
    """Запускает параллельный сбор по всем 5 темам."""
    tasks = {k: fetch_category_repos(k) for k in CATEGORIES.keys()}
    results = {}
    for key, task in tasks.items():
        results[key] = await task
    return results
