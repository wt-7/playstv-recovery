import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator
import aiohttp
from aiolimiter import AsyncLimiter
from rich.text import Text
import argparse
from playstv_recovery.cache import Cache
from playstv_recovery.downloader import DownloadClient
from playstv_recovery.scraper import VideoLinkScraper
from playstv_recovery.console import console
from dataclasses import dataclass, field
from rich.table import Table
from rich.live import Live
from rich.panel import Panel


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)

# Wayback Machine rate limit
RATE_LIMIT = 14

SAVE_DIR = Path("plays-tv-videos")
CACHE_PATH = SAVE_DIR / "cache"


def print_logo():
    text = Text(
        """
▗▄▄▖ █ ▗▞▀▜▌▄   ▄  ▄▄▄ ▗▄▄▄▖▗▖  ▗▖    ▗▄▄▖ ▗▞▀▚▖▗▞▀▘ ▄▄▄  ▄   ▄ ▗▞▀▚▖ ▄▄▄ ▄   ▄ 
▐▌ ▐▌█ ▝▚▄▟▌█   █ ▀▄▄    █  ▐▌  ▐▌    ▐▌ ▐▌▐▛▀▀▘▝▚▄▖█   █ █   █ ▐▛▀▀▘█    █   █ 
▐▛▀▘ █       ▀▀▀█ ▄▄▄▀   █  ▐▌  ▐▌    ▐▛▀▚▖▝▚▄▄▖    ▀▄▄▄▀  ▀▄▀  ▝▚▄▄▖█     ▀▀▀█ 
▐▌   █      ▄   █        █   ▝▚▞▘     ▐▌ ▐▌                               ▄   █ 
             ▀▀▀                                                           ▀▀▀  
                                                                                
                                                                                """,
        style="bold cyan",
    )
    console.print(text)


@asynccontextmanager
async def create_session() -> AsyncIterator[aiohttp.ClientSession]:
    """Create and manage an aiohttp session."""
    connector = aiohttp.TCPConnector(
        ttl_dns_cache=300,
    )
    timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=60)
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
    ) as session:
        yield session


@dataclass
class Stats:
    found: int = 0
    completed: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def inc_found(self):
        async with self._lock:
            self.found += 1

    async def inc_completed(self):
        async with self._lock:
            self.completed += 1


def render_stats(stats: Stats) -> Panel:
    """Render a rich panel with live stats."""
    table = Table(title="Download Progress", expand=True, show_header=False, box=None)
    table.add_row("🔎 Videos Found:", f"[cyan]{stats.found}[/cyan]")
    table.add_row("✅ Videos Completed:", f"[green]{stats.completed}[/green]")
    table.add_row(
        "⏳ Remaining:", f"[yellow]{max(stats.found - stats.completed, 0)}[/yellow]"
    )
    return Panel(table, border_style="bold blue")


async def run(
    args: argparse.Namespace,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    rate_limiter: AsyncLimiter,
):
    stats = Stats()
    user_download_path = SAVE_DIR / str(args.username)
    user_download_path.mkdir(parents=True, exist_ok=True)
    console.print(f"[bold]Saving videos to:[/bold] {user_download_path.resolve()}")

    client = DownloadClient(
        session=session,
        semaphore=semaphore,
        rate_limiter=rate_limiter,
        save_path=user_download_path,
    )
    cache = Cache(CACHE_PATH)
    scraper = VideoLinkScraper(user_agent=USER_AGENT, headless=not args.show_browser)

    async def worker(url: str, live: Live):
        if url not in cache:
            await client.download(url)
            await cache.add(url)
        await stats.inc_completed()
        live.update(render_stats(stats))

    with Live(
        render_stats(stats),
        refresh_per_second=4,
        console=console,
    ) as live:
        tasks = []
        async for video_url in scraper.stream_urls(args.username):
            await stats.inc_found()
            live.update(render_stats(stats))
            tasks.append(asyncio.create_task(worker(video_url, live)))

        await asyncio.gather(*tasks, return_exceptions=True)

    console.print("[bold green]🎉 All downloads completed![/bold green]")


async def async_main():
    parser = argparse.ArgumentParser(
        description="Download plays.tv videos from Wayback Machine."
    )
    parser.add_argument(
        "username",
        type=str,
        help="PlaysTV username to archive",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show the browser window (for debugging)",
    )

    args = parser.parse_args()

    print_logo()

    semaphore = asyncio.Semaphore(10)
    rate_limiter = AsyncLimiter(RATE_LIMIT)

    async with create_session() as session:
        await run(
            session=session,
            args=args,
            semaphore=semaphore,
            rate_limiter=rate_limiter,
        )


def main():
    asyncio.run(async_main())
