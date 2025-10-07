import asyncio
import argparse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Callable, Awaitable

import aiohttp
from aiolimiter import AsyncLimiter
from rich.text import Text

from playstv_recovery.cache import Cache
from playstv_recovery.downloader import DownloadClient
from playstv_recovery.scraper import TotalFound, UrlFound, VideoLinkScraper
from playstv_recovery.console import console
from playstv_recovery.stats import DownloadStats, LiveStatsDisplay, print_report

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
RATE_LIMIT = 14
NUM_WORKERS = 20
SAVE_DIR = Path("plays-tv-videos")
CACHE_PATH = SAVE_DIR / "cache.txt"


def print_logo() -> None:
    logo = """
▗▄▄▖ █ ▗▞▀▜▌▄   ▄  ▄▄▄ ▗▄▄▄▖▗▖  ▗▖    ▗▄▄▖ ▗▞▀▚▖▗▞▀▘ ▄▄▄  ▄   ▄ ▗▞▀▚▖ ▄▄▄ ▄   ▄ 
▐▌ ▐▌█ ▝▚▄▟▌█   █ ▀▄▄    █  ▐▌  ▐▌    ▐▌ ▐▌▐▛▀▀▘▝▚▄▖█   █ █   █ ▐▛▀▀▘█    █   █ 
▐▛▀▘ █       ▀▀▀█ ▄▄▄▀   █  ▐▌  ▐▌    ▐▛▀▚▖▝▚▄▄▖    ▀▄▄▄▀  ▀▄▀  ▝▚▄▄▖█     ▀▀▀█ 
▐▌   █      ▄   █        █   ▝▚▞▘     ▐▌ ▐▌                               ▄   █ 
             ▀▀▀                                                           ▀▀▀  
"""

    console.print(Text(logo, style="bold cyan"))


def create_user_directory(username: str) -> Path:
    """Create and return the user's download directory"""

    user_path = SAVE_DIR / username
    user_path.mkdir(parents=True, exist_ok=True)
    return user_path


@asynccontextmanager
async def create_session() -> AsyncIterator[aiohttp.ClientSession]:
    """Create and manage an aiohttp ClientSession with proper configuration."""

    connector = aiohttp.TCPConnector(ttl_dns_cache=300)
    timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=60)
    headers = {"User-Agent": USER_AGENT}

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers,
    ) as session:
        yield session


async def produce_urls(
    scraper: VideoLinkScraper, username: str, queue: asyncio.Queue, stats: DownloadStats
) -> None:
    """Scrape video URLs and enqueue them for downloading."""

    loop = asyncio.get_running_loop()

    def scrape_sync(event_loop: asyncio.AbstractEventLoop) -> None:
        """Synchronous scraping function to run in thread."""

        for event in scraper.scrape_urls(username):
            match event:
                case TotalFound(total):
                    asyncio.run_coroutine_threadsafe(stats.set_total(total), event_loop)
                case UrlFound(url):
                    asyncio.run_coroutine_threadsafe(
                        stats.increment_found(), event_loop
                    )
                    asyncio.run_coroutine_threadsafe(queue.put(url), event_loop)

    await asyncio.to_thread(scrape_sync, loop)
    await queue.put(None)  # Sentinel value


async def consume_queue(
    queue: asyncio.Queue,
    process_fn: Callable[[str], Awaitable[None]],
) -> None:
    """Consume URLs from queue until sentinel is received."""

    while True:
        url = await queue.get()

        if url is None:  # Sentinel value
            queue.task_done()
            queue.put_nowait(None)  # Propagate to other workers
            break

        try:
            await process_fn(url)
        finally:
            queue.task_done()


async def run(
    username: str,
    show_browser: bool,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    rate_limiter: AsyncLimiter,
) -> None:
    """Execute the complete download pipeline."""

    stats = DownloadStats()
    save_path = create_user_directory(username)
    console.print(f"[bold]Saving videos to:[/bold] {save_path.resolve()}")

    client = DownloadClient(
        session=session,
        semaphore=semaphore,
        rate_limiter=rate_limiter,
        save_path=save_path,
    )
    cache = Cache(CACHE_PATH)
    scraper = VideoLinkScraper(user_agent=USER_AGENT, headless=not show_browser)
    queue: asyncio.Queue = asyncio.Queue()

    async def download_worker(url: str) -> None:
        if url in cache:
            await stats.increment_skipped()
            return
        try:
            path = await client.download(url)
            await cache.add(url)
            await stats.increment_completed(path.name)

        except Exception as e:
            await stats.increment_failed()
            console.print(f"[red]Error downloading {url}: {e}[/red]")

    with LiveStatsDisplay(stats):

        producer_task = asyncio.create_task(
            produce_urls(scraper, username, queue, stats)
        )

        worker_tasks = [
            asyncio.create_task(consume_queue(queue, download_worker))
            for _ in range(NUM_WORKERS)
        ]

        await producer_task
        await queue.join()
        await asyncio.gather(*worker_tasks, return_exceptions=True)

    print_report(stats)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""

    parser = argparse.ArgumentParser(
        description="Download plays.tv videos from Wayback Machine.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
    return parser.parse_args()


async def async_main() -> None:
    """Main async entry point for the application."""

    args = parse_args()
    print_logo()

    semaphore = asyncio.Semaphore(NUM_WORKERS)
    rate_limiter = AsyncLimiter(RATE_LIMIT)

    async with create_session() as session:
        await run(
            username=args.username,
            show_browser=args.show_browser,
            session=session,
            semaphore=semaphore,
            rate_limiter=rate_limiter,
        )


def main() -> None:
    """Main entry point for the application."""

    asyncio.run(async_main())
