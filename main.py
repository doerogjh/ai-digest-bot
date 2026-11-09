import sys
import os
import asyncio
import argparse
from pathlib import Path

# Убеждаемся, что текущая папка есть в путях
CURRENT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(CURRENT_DIR))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from dotenv import load_dotenv

import database
from scraper import CATEGORIES, fetch_all_categories, fetch_category_repos
from summarizer import summarize_repo

load_dotenv()
console = Console()

async def run_cli_mode():
    """Интерактивный режим работы прямо в терминале."""
    await database.init_db()
    console.print(Panel.fit(
        "[bold cyan]🚀 AI IT & GitHub Digest — Консольный режим[/bold cyan]\n"
        "[dim]Парсинг тем: ИИ, Хакинг, Программирование, DevOps, Полезные тулзы[/dim]",
        border_style="cyan"
    ))

    # Проверка наличия данных в памяти
    stats = await database.get_stats()
    if stats["total_repos"] == 0:
        with console.status("[bold green]Сканирую GitHub по 5 категориям и обучаю локальную память...[/bold green]"):
            data = await fetch_all_categories()
            for cat_key, repos in data.items():
                await database.save_repos(repos, cat_key)
        stats = await database.get_stats()

    console.print(f"[bold green]✓[/bold green] В памяти на компьютере: [bold yellow]{stats['total_repos']}[/bold yellow] проектов.\n")

    # Меню выбора тем
    console.print("[bold]Доступные темы:[/bold]")
    cat_keys = list(CATEGORIES.keys())
    for i, (k, v) in enumerate(CATEGORIES.items(), 1):
        console.print(f"  [bold cyan]{i}[/bold cyan]. {v['title']}")
    console.print(f"  [bold cyan]6[/bold cyan]. 🔄 Принудительно обновить память с GitHub")
    console.print(f"  [bold cyan]0[/bold cyan]. Выход\n")

    while True:
        try:
            choice = input("Выбери номер темы (0-6): ").strip()
            if choice == "0":
                console.print("[dim]До скорой встречи![/dim]")
                break
            if choice == "6":
                with console.status("[bold green]Обновляю базу с GitHub...[/bold green]"):
                    data = await fetch_all_categories()
                    for cat_key, repos in data.items():
                        await database.save_repos(repos, cat_key)
                console.print("[bold green]✓ Память успешно обновлена свежими репозиториями![/bold green]\n")
                continue

            idx = int(choice) - 1
            if 0 <= idx < len(cat_keys):
                selected_cat = cat_keys[idx]
                repos = await database.get_repos_by_category(selected_cat, limit=10)

                table = Table(title=f"Топ репозиториев: {CATEGORIES[selected_cat]['title']}", show_header=True, header_style="bold magenta")
                table.add_column("№", style="dim", width=4)
                table.add_column("Репозиторий", style="bold cyan")
                table.add_column("Звезды", style="yellow")
                table.add_column("Описание")

                for i, r in enumerate(repos, 1):
                    desc = (r.get("description") or "—")[:70]
                    table.add_row(str(i), r["repo_id"], f"⭐ {r.get('stars', '0')}", desc)

                console.print(table)

                # Выбор для детального AI-разбора
                repo_choice = input("\nВведи номер проекта для детального AI-разбора (Enter - назад): ").strip()
                if repo_choice.isdigit():
                    r_idx = int(repo_choice) - 1
                    if 0 <= r_idx < len(repos):
                        target_repo = repos[r_idx]
                        with console.status("[bold magenta]Генерирую AI-карточку...[/bold magenta]"):
                            summary = await summarize_repo(target_repo)
                        console.print("\n", Markdown(summary), "\n")
            else:
                console.print("[red]Неверный номер, попробуй ещё раз.[/red]")
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            console.print(f"[red]Ошибка: {e}[/red]")

def main():
    parser = argparse.ArgumentParser(description="AI IT & GitHub Digest Bot")
    parser.add_argument("--cli", action="store_true", help="Запустить в консольном режиме прямо в терминале")
    parser.add_argument("--bot", action="store_true", help="Запустить Telegram-бота")
    args = parser.parse_args()

    # По умолчанию если передан флаг --cli
    if args.cli:
        asyncio.run(run_cli_mode())
    else:
        # Проверяем наличие токена
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token or "YOUR_TELEGRAM_BOT_TOKEN" in token:
            print("💡 Токен Telegram-бота пока не найден в .env. Запускаем консольный режим CLI...")
            asyncio.run(run_cli_mode())
        else:
            from bot import run_bot
            asyncio.run(run_bot())

if __name__ == "__main__":
    main()
