import time
from typing import Iterator
from dataclasses import dataclass
from contextlib import contextmanager

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions

WAYBACK_URL = "https://web.archive.org/web/"
PLAYS_TV_URL = "https://web.archive.org/web/20191210043532/https://plays.tv/u/"

# Maximum number of times the scraper will attempt to scroll to load more videos
MAX_SCROLL_ATTEMPTS = 50
# Maximum number of consecutive scroll attempts that yield no new videos before stopping
MAX_FAIL_ATTEMPTS = 10


@dataclass
class TotalFound:
    count: int


@dataclass
class UrlFound:
    url: str


ScrapeEvent = TotalFound | UrlFound


class VideoLinkScraper:
    """Scrape video page links from a user's PlaysTV profile."""

    def __init__(
        self,
        user_agent: str,
        sleep_time: int = 4,
        headless: bool = False,
    ) -> None:
        self.sleep_time = sleep_time
        self.user_agent = user_agent
        self.headless = headless

    @contextmanager
    def _get_driver(self):
        """Context manager for Chrome webdriver."""
        options = ChromeOptions()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument(f"--user-agent={self.user_agent}")

        driver = webdriver.Chrome(options=options)
        try:
            yield driver
        finally:
            driver.quit()

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

        new_urls = []
        for element in elements:
            if href := element.get_attribute("href"):
                # Strip query parameters and prepend Wayback URL
                url = f"{WAYBACK_URL}{href.split('?')[0]}"
                if url not in seen_urls:
                    new_urls.append(url)

        return new_urls

    def _scroll_to_bottom(self, driver: webdriver.Chrome) -> None:
        """Scroll to the bottom of the page."""
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

    def _should_stop_scrolling(
        self, seen_count: int, target_count: int, consecutive_fails: int
    ) -> bool:
        """Determine if scrolling should stop."""
        reached_target = target_count > 0 and seen_count >= target_count
        too_many_fails = consecutive_fails >= MAX_FAIL_ATTEMPTS
        return reached_target or too_many_fails

    def scrape_urls(self, username: str) -> Iterator[ScrapeEvent]:
        """
        Scrape video URLs from the specified user's profile.

        Yields:
            ScrapeEvent: TotalFound event followed by UrlFound events for each video.
        """
        with self._get_driver() as driver:
            driver.get(f"{PLAYS_TV_URL}{username}")

            seen_urls: set[str] = set()
            consecutive_fails = 0
            target_count = self._get_user_video_count(driver)

            # Inform the caller of the total number of videos to expect
            yield TotalFound(count=target_count)

            for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
                self._scroll_to_bottom(driver)

                # Don't wait on the first attempt, as webdriver waits for initial page load
                if attempt > 1:
                    time.sleep(self.sleep_time)

                new_urls = self._extract_new_video_urls(driver, seen_urls)

                # Yield each new URL as it's found
                yield from (UrlFound(url=url) for url in new_urls)

                seen_urls.update(new_urls)

                if self._should_stop_scrolling(
                    len(seen_urls), target_count, consecutive_fails
                ):
                    break

                # Update consecutive fails counter
                consecutive_fails = consecutive_fails + 1 if not new_urls else 0
