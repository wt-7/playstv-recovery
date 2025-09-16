from pathlib import Path
from dataclasses import dataclass
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import requests
import shortuuid
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from bs4 import Tag
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
    MofNCompleteColumn,
)
from rich.panel import Panel
from rich.text import Text
import argparse


WAYBACK_URL = "https://web.archive.org/web/"
PLAYS_TV_URL = "https://web.archive.org/web/20191210043532/https://plays.tv/u/"
SAVE_DIR = Path("playstv-archive")
CHUNK_SIZE = 8192
CONSOLE = Console()


@dataclass
class Video:
    title: str
    source: str

    @property
    def safe_filename(self) -> str:
        return f"{self.title}_{shortuuid.uuid()}.mp4"


@dataclass
class DownloadStats:
    successful: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.successful + self.failed


def init_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=1,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
    )
    return session


def init_driver() -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
    return webdriver.Chrome(options=options)


def scroll_to_bottom(driver: webdriver.Chrome):
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(5)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break

        last_height = new_height


def get_video_urls(driver: webdriver.Chrome, username: str) -> list[str]:
    driver.get(PLAYS_TV_URL + username)
    scroll_to_bottom(driver)
    elements = driver.find_elements(
        By.CSS_SELECTOR, ".bd .video-list-container a.title"
    )

    video_urls = []
    for element in elements:
        href = element.get_attribute("href")
        if href:
            video_url, _ = href.split("?")
            video_urls.append(f"{WAYBACK_URL}{video_url}")

    return video_urls


def get_video_source(url: str, session: requests.Session) -> str:
    response = session.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")
    source_tag = soup.find("source", {"res": "720"})

    if isinstance(source_tag, Tag):
        return f"https:{source_tag.get('src')}"
    else:
        raise ValueError("Video source not found")


def download_video(video: Video, session: requests.Session, save_to: Path):
    with session.get(video.source, stream=True) as response:
        response.raise_for_status()
        with open(save_to, "wb") as f:
            for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)


def fetch_video_urls(username: str) -> list[str]:
    """Fetch all video URLs for a given username."""
    with CONSOLE.status(f"[bold blue]Fetching video URLs for {username}..."):
        with init_driver() as driver:
            video_urls = get_video_urls(driver=driver, username=username)

    if not video_urls:
        CONSOLE.print(f"[red]No videos found for {username}. Exiting.[/red]")
        return []

    CONSOLE.print(f"[green]✓[/green] Found {len(video_urls)} videos for {username}")
    return video_urls


def setup_download_directory(username: str) -> Path:
    """Create and return the download directory path."""
    save_directory = SAVE_DIR / username
    save_directory.mkdir(parents=True, exist_ok=True)
    return save_directory


def process_single_video(
    url: str, session: requests.Session, save_directory: Path
) -> bool:
    """Process and download a single video. Returns True if successful."""
    video_name = url.split("/")[-1]

    try:
        video = Video(title=video_name, source=get_video_source(url, session))
        save_path = save_directory / video.safe_filename

        download_video(video=video, session=session, save_to=save_path)
        CONSOLE.print(f"[green]✓[/green] Saved: [dim]{save_path.name}[/dim]")
        return True

    except Exception as e:
        CONSOLE.print(
            f"[red]✗[/red] Failed: [dim]{video_name}[/dim] - {str(e)[:60]}..."
        )
        return False


def download_all_videos(video_urls: list[str], save_directory: Path) -> DownloadStats:
    """Download all videos and return statistics."""
    session = init_session()
    stats = DownloadStats()

    with progress_bar() as progress:
        main_task = progress.add_task(
            "[bold green]Downloading videos...", total=len(video_urls)
        )

        for i, url in enumerate(video_urls, 1):
            video_name = url.split("/")[-1]

            progress.update(
                main_task,
                description=f"[bold green]Processing[/bold green] [dim]({i}/{len(video_urls)})[/dim] {video_name[:50]}...",
            )

            if process_single_video(url, session, save_directory):
                stats.successful += 1
            else:
                stats.failed += 1

            progress.update(main_task, advance=1)

    return stats


def print_summary(stats: DownloadStats, save_directory: Path):
    """Display the final download summary."""
    summary_text = (
        Text()
        .append("Download Complete!\n", style="bold green")
        .append(f"✓ Successful: {stats.successful}\n", style="green")
    )

    if stats.failed > 0:
        summary_text.append(f"✗ Failed: {stats.failed}\n", style="red")
    summary_text.append(f"📁 Saved to: {save_directory}", style="dim")

    summary_panel = Panel(
        summary_text,
        title="[bold]Summary[/bold]",
        border_style="green" if stats.failed == 0 else "yellow",
    )
    CONSOLE.print(summary_panel)


def progress_bar() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=CONSOLE,
        expand=True,
    )


def print_download_info(video_count: int, username: str, save_directory: Path):
    """Display information panel about the download."""
    info_panel = Panel(
        f"[bold]Downloading {video_count} videos[/bold]\n"
        f"[dim]Username:[/dim] {username}\n"
        f"[dim]Save directory:[/dim] {save_directory}",
        title="[bold blue]Download Info[/bold blue]",
        border_style="blue",
    )
    CONSOLE.print(info_panel)


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
    CONSOLE.print(text)


def main():
    """Main entry point for the video downloader."""

    parser = argparse.ArgumentParser(
        description="Download plays.tv videos from Wayback Machine."
    )
    parser.add_argument(
        "-u",
        "--username",
        type=str,
        required=True,
        help="Plays.tv username to archive",
    )
    args = parser.parse_args()
    print_logo()

    # Fetch video URLs
    video_urls = fetch_video_urls(args.username)
    if not video_urls:
        return

    # Setup download environment
    save_directory = setup_download_directory(args.username)
    print_download_info(len(video_urls), args.username, save_directory)

    # Download all videos
    stats = download_all_videos(video_urls, save_directory)

    # Display final summary
    print_summary(stats, save_directory)


if __name__ == "__main__":
    main()
