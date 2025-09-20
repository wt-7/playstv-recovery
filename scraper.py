import asyncio
from collections.abc import AsyncGenerator
from itertools import filterfalse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions
from console import console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
)


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
WAYBACK_URL = "https://web.archive.org/web/"
PLAYS_TV_URL = "https://web.archive.org/web/20191210043532/https://plays.tv/u/"

MAX_SCROLL_ATTEMPTS = 50
MAX_FAIL_ATTEMPTS = 10


def get_webdriver_options() -> ChromeOptions:
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument(f"--user-agent={USER_AGENT}")
    return options


def show_progress_bar():
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    )


class VideoLinkScraper:
    """Scrapes video URLs from plays.tv user pages."""

    def __init__(self, sleep_time: int = 4) -> None:
        self.sleep_time = sleep_time

    def _get_user_video_count(self, driver: webdriver.Chrome) -> int:
        """Get the total number of videos listed on the user's profile."""

        video_count_element = driver.find_element(
            By.CSS_SELECTOR, ".nav-tab-label span"
        )

        return int(video_count_element.text)

    def _extract_new_video_urls(
        self, driver: webdriver.Chrome, seen_urls: set[str]
    ) -> list[str]:
        """Extract video URLs that haven't been seen before."""

        elements = driver.find_elements(
            By.CSS_SELECTOR, ".bd .video-list-container a.title"
        )

        hrefs = (element.get_attribute("href") for element in elements)
        valid_hrefs = filter(None, hrefs)
        processed_urls = (WAYBACK_URL + href.split("?")[0] for href in valid_hrefs)

        return [url for url in processed_urls if url not in seen_urls]

    async def stream_urls(self, username: str) -> AsyncGenerator[str, None]:
        """Stream video URLs as they're discovered."""
        console.print(f"[bold blue]Streaming video URLs for {username}...[/bold blue]")

        with webdriver.Chrome(options=get_webdriver_options()) as driver:
            driver.get(PLAYS_TV_URL + username)

            seen_urls: set[str] = set()
            consecutive_fails = 0
            target_count = self._get_user_video_count(driver)

            console.print(
                f"[dim]Target count: {target_count if target_count > 0 else 'unknown'}[/dim]"
            )

            for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                if attempt != 1:
                    await asyncio.sleep(self.sleep_time)

                new_urls = self._extract_new_video_urls(driver, seen_urls)

                for url in new_urls:
                    yield url

                seen_urls.update(new_urls)
                new_count = len(new_urls)

                # Check completion conditions
                reached_target = target_count > 0 and len(seen_urls) >= target_count
                no_new_videos_found = new_count == 0

                if reached_target:
                    console.print(f"[green]✓ Found all {len(seen_urls)} videos[/green]")
                    break

                elif no_new_videos_found:
                    consecutive_fails += 1
                    console.print(
                        f"[yellow]⚠️ Attempt {attempt}:[/yellow] No new videos loaded "
                        f"[dim](fail {consecutive_fails}/{MAX_FAIL_ATTEMPTS})[/dim]"
                    )
                    if consecutive_fails >= MAX_SCROLL_ATTEMPTS:
                        console.print(
                            f"[red]Stopping with {len(seen_urls)} videos[/red]"
                        )
                        break

                else:
                    consecutive_fails = 0
                    console.print(
                        f"[green]Found {new_count} new videos (total: {len(seen_urls)})[/green]"
                    )
