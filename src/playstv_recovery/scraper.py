import asyncio
from collections.abc import AsyncGenerator
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options as ChromeOptions


WAYBACK_URL = "https://web.archive.org/web/"
PLAYS_TV_URL = "https://web.archive.org/web/20191210043532/https://plays.tv/u/"

# Maximum number of times the scraper will attempt to scroll to load more videos
MAX_SCROLL_ATTEMPTS = 50

# Maximum number of consecutive scroll attempts that yield no new videos before stopping
MAX_FAIL_ATTEMPTS = 10


class VideoLinkScraper:
    """Scrape video page links from a user's PlaysTV profile."""

    def __init__(
        self,
        user_agent: str,
        sleep_time: int = 4,
        headless: bool = False,
    ) -> None:
        self.sleep_time = sleep_time
        self.options = ChromeOptions()

        if headless:
            self.options.add_argument("--headless=new")

        self.options.add_argument(f"--user-agent={user_agent}")

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

        with webdriver.Chrome(options=self.options) as driver:
            driver.get(PLAYS_TV_URL + username)

            seen_urls: set[str] = set()
            consecutive_fails = 0
            target_count = self._get_user_video_count(driver)

            for attempt in range(1, MAX_SCROLL_ATTEMPTS + 1):
                # Scroll to the bottom to trigger loading more videos
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                # Don't wait on the first attempt, as the webdriver will wait for the initial page load
                if attempt != 1:
                    await asyncio.sleep(self.sleep_time)

                new_urls = self._extract_new_video_urls(driver, seen_urls)

                for url in new_urls:
                    # Yield each new URL as it's found
                    yield url

                seen_urls.update(new_urls)
                new_count = len(new_urls)

                reached_target = target_count > 0 and len(seen_urls) >= target_count
                no_new_videos_found = new_count == 0

                if reached_target:
                    # All of the videos have been found as per the user's video count
                    break

                elif no_new_videos_found:
                    consecutive_fails += 1
                    if consecutive_fails >= MAX_FAIL_ATTEMPTS:
                        # Too many consecutive scrolls with no new videos found, stop scrolling
                        break

                else:
                    # New videos were found, reset the fail counter and scroll again
                    consecutive_fails = 0
