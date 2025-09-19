import time
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
from rich.panel import Panel


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)
WAYBACK_URL = "https://web.archive.org/web/"
PLAYS_TV_URL = "https://web.archive.org/web/20191210043532/https://plays.tv/u/"

MAX_SCROLL_ATTEMPTS = 50
MAX_FAIL_ATTEMPTS = 5


def init_webdriver() -> webdriver.Chrome:
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(f"--user-agent={USER_AGENT}")
    return webdriver.Chrome(options=options)


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


class ProfilePageScraper:
    """Fetches video URLs from plays.tv user pages."""

    def __init__(self, sleep_time: int = 3) -> None:
        self.sleep_time = sleep_time

    def _get_user_video_count(self, driver: webdriver.Chrome) -> int:
        """Get the total number of videos listed on the user's profile."""
        video_count_element = driver.find_element(
            By.CSS_SELECTOR, ".info-links .section-value"
        )
        return int(video_count_element.text)

    def _scroll_to_end(self, driver: webdriver.Chrome) -> None:
        """Scroll until we find all videos or hit max attempts."""

        fails = 0
        prev_count = 0

        target_count = self._get_user_video_count(driver)
        console.print(
            Panel(
                f"🎯 [bold blue]User has {target_count} videos. Attempting to load...[/bold blue]",
                expand=False,
            )
        )

        with show_progress_bar() as progress:
            task = progress.add_task("Loading videos...", total=target_count)

            for attempt in range(MAX_SCROLL_ATTEMPTS):
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(self.sleep_time)

                current_count = len(
                    driver.find_elements(
                        By.CSS_SELECTOR, ".bd .video-list-container a.title"
                    )
                )

                progress.update(task, completed=current_count)

                hit_target = target_count > 0 and current_count >= target_count
                if hit_target:
                    progress.update(task, description="[green]✅ Complete!")
                    console.print(
                        f"[bold green]🎉 Success![/bold green] Found all [bold]{current_count}[/bold] videos"
                    )
                    break

                elif current_count == prev_count:
                    fails += 1
                    progress.update(
                        task,
                        description=f"[yellow]⚠️ No new videos (fail {fails}/{MAX_FAIL_ATTEMPTS})",
                    )
                    console.print(
                        f"[yellow]⚠️ Attempt {attempt + 1}:[/yellow] No new videos loaded [dim](fail {fails}/{MAX_FAIL_ATTEMPTS})[/dim]"
                    )

                    if fails >= MAX_FAIL_ATTEMPTS:
                        progress.update(
                            task, description="[red]❌ Max failures reached"
                        )
                        console.print(
                            f"[red]🛑 Stopping with {current_count} videos[/red]"
                        )
                        break
                else:
                    # New videos found
                    new_videos = current_count - prev_count
                    fails = 0
                    prev_count = current_count
                    progress.update(
                        task, description=f"[green]📈 Found {new_videos} new videos"
                    )
                    console.print(
                        f"[green]📈 Attempt {attempt + 1}:[/green] Found [bold]{new_videos}[/bold] new videos [dim](total: {current_count})[/dim]"
                    )

                if attempt == MAX_SCROLL_ATTEMPTS - 1:
                    progress.update(task, description="[red]⏰ Max attempts reached")
                    console.print(
                        f"[red]⏰ Max scroll attempts reached[/red] [dim]({MAX_SCROLL_ATTEMPTS})[/dim]"
                    )
                    console.print(
                        f"[yellow]📋 Final count: {current_count} videos[/yellow]"
                    )

    def fetch_urls(self, username: str) -> list[str]:
        """Fetch all availablevideo page URLs for a given username."""
        console.print(f"[bold blue]Fetching video URLs for {username}...[/bold blue]")

        with init_webdriver() as driver:
            driver.get(PLAYS_TV_URL + username)
            time.sleep(self.sleep_time)

            self._scroll_to_end(driver)

            elements = driver.find_elements(
                By.CSS_SELECTOR, ".bd .video-list-container a.title"
            )
            hrefs = [element.get_attribute("href") for element in elements]
            video_urls = [WAYBACK_URL + href.split("?")[0] for href in hrefs if href]

            if not video_urls:
                console.print(f"[red]No videos found for {username}[/red]")
            else:
                console.print(
                    f"[green]✓[/green] Found {len(video_urls)} videos for {username}"
                )

            return video_urls
