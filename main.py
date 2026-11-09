import sys
import os
import asyncio
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta

CURRENT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(CURRENT_DIR))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from dotenv import load_dotenv

import database
from scraper import CATEGORIES, fetch_all_categories
from summarizer import summarize_repo

load_dotenv()
console = Console()

async def run_cli_mode():
    """Интерактивный терминальный режим с поддержкой архива по датам и машины времени."""
    await database.init_db()
    current_date = database.get_current_date_str()

    stats = await database.get_memory_stats()
    if stats["days_count"] == 0:
        with console.status("[bold green]Первичный сбор GitHub и создание архива на сегодня...[/bold green]"):
            data = await fetch_all_categories()
            for cat_key, repos in data.items():
                await database.save_daily_snapshot(repos, cat_key, current_date)
        stats = await database.get_memory_stats()

    while True:
        console.clear()
        stats = await database.get_memory_stats()
        console.print(Panel.fit(
            f"[bold cyan]🧠 AI GitHub Digest — Память и Машина времени[/bold cyan]\n"
            f"[bold yellow]📅 Активная дата архива:[/bold yellow] [bold green]{current_date}[/bold green]\n"
            f"[dim]Всего сохранено дней в памяти ПК: {stats['days_count']} ({stats['history_records']} записей в архиве)[/dim]",
            border_style="cyan"
        ))

        console.print("[bold]Категории за выбранную дату:[/bold]")
        cat_keys = list(CATEGORIES.keys())
        for i, (k, v) in enumerate(CATEGORIES.items(), 1):
            console.print(f"  [bold cyan]{i}[/bold cyan]. {v['title']}")

        console.print("\n[bold]Машина времени и память:[/bold]")
        console.print(f"  [bold magenta]7[/bold magenta]. ⏳ Сменить дату (Вчера, Месяц назад, Год назад)")
        console.print(f"  [bold magenta]8[/bold magenta]. 🔍 Поиск по всей истории памяти")
        console.print(f"  [bold magenta]9[/bold magenta]. 🔄 Собрать свежий срез на сегодня ({database.get_current_date_str()})")
        console.print(f"  [bold red]0[/bold red]. Выход\n")

        try:
            choice = input("Выбери действие (0-9): ").strip()
            if choice == "0":
                console.print("[dim]До скорой встречи![/dim]")
                break

            elif choice == "7":
                # Смена даты
                dates = await database.get_history_dates()
                console.print("\n[bold]Доступные даты в архиве памяти:[/bold]")
                for idx, d in enumerate(dates, 1):
                    tag = " (Сегодня)" if d == database.get_current_date_str() else ""
                    console.print(f"  [bold cyan]{idx}[/bold cyan]. 📅 {d}{tag}")
                d_choice = input("\nВведи номер даты для загрузки: ").strip()
                if d_choice.isdigit():
                    d_idx = int(d_choice) - 1
                    if 0 <= d_idx < len(dates):
                        current_date = dates[d_idx]
                        console.print(f"[bold green]Загружен архив за {current_date}![/bold green]")
                        input("Нажми Enter для продолжения...")
                continue

            elif choice == "8":
                # Поиск по памяти
                q = input("\nВведи слово для поиска по всей сохраненной памяти: ").strip()
                if q:
                    results = await database.search_memory(q)
                    if results:
                        table = Table(title=f"Результаты поиска по памяти: '{q}'", show_header=True)
                        table.add_column("Дата", style="magenta")
                        table.add_column("Репозиторий", style="bold cyan")
                        table.add_column("Звезды", style="yellow")
                        table.add_column("Описание")
                        for r in results:
                            table.add_row(r.get("snapshot_date", "—"), r["repo_id"], f"⭐ {r.get('stars', '0')}", (r.get("description") or "")[:60])
                        console.print(table)
                    else:
                        console.print("[yellow]Ничего не найдено в архиве памяти.[/yellow]")
                input("\nНажми Enter для возврата...")
                continue

            elif choice == "9":
                with console.status("[bold green]Сканирую GitHub и сохраняю срез на сегодня...[/bold green]"):
                    data = await fetch_all_categories()
                    today = database.get_current_date_str()
                    for cat_key, repos in data.items():
                        await database.save_daily_snapshot(repos, cat_key, today)
                    current_date = today
                console.print("[bold green]✓ Срез на сегодня сохранен навсегда в память ПК![/bold green]")
                input("Нажми Enter для продолжения...")
                continue

            elif choice.isdigit() and 1 <= int(choice) <= len(cat_keys):
                selected_cat = cat_keys[int(choice) - 1]
                repos = await database.get_repos_by_date_and_category(current_date, selected_cat, limit=20)

                if not repos:
                    console.print(f"[yellow]За дату {current_date} в категории '{CATEGORIES[selected_cat]['title']}' записей нет.[/yellow]")
                    input("Нажми Enter...")
                    continue

                table = Table(
                    title=f"{CATEGORIES[selected_cat]['title']} | Архив за {current_date}",
                    show_header=True,
                    header_style="bold magenta"
                )
                table.add_column("№", style="dim", width=4)
                table.add_column("Репозиторий", style="bold cyan")
                table.add_column("Звезды", style="yellow")
                table.add_column("Описание")

                for i, r in enumerate(repos[:15], 1):
                    desc = (r.get("description") or "—")[:65]
                    table.add_row(str(i), r["repo_id"], f"⭐ {r.get('stars', '0')}", desc)

                console.print(table)

                repo_choice = input("\nВведи номер проекта для полного разбора (Enter - назад): ").strip()
                if repo_choice.isdigit():
                    r_idx = int(repo_choice) - 1
                    if 0 <= r_idx < len(repos):
                        target_repo = repos[r_idx]
                        with console.status("[bold magenta]Извлекаю разбор из памяти...[/bold magenta]"):
                            summary = await summarize_repo(target_repo)
                        console.print("\n", Markdown(summary), "\n")
                        input("Нажми Enter для возврата в меню...")
            else:
                console.print("[red]Неверный ввод.[/red]")
                input("Нажми Enter...")

        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            console.print(f"[red]Ошибка: {e}[/red]")
            input("Нажми Enter...")

def main():
    parser = argparse.ArgumentParser(description="AI IT & GitHub Digest Bot")
    parser.add_argument("--cli", action="store_true", help="Запустить в консольном режиме")
    parser.add_argument("--bot", action="store_true", help="Запустить Telegram-бота")
    args = parser.parse_args()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if args.cli or not token or "YOUR_TELEGRAM_BOT_TOKEN" in token:
        asyncio.run(run_cli_mode())
    else:
        from bot import run_bot
        asyncio.run(run_bot())

if __name__ == "__main__":
    main()
