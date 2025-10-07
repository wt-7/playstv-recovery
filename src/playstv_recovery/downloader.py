import asyncio
from pathlib import Path

import aiofiles
import aiohttp
from bs4 import BeautifulSoup, Tag
from aiolimiter import AsyncLimiter

CHUNK_SIZE = 8192


def extract_video_source(content: bytes):
    """Extracts the video source URL from the HTML content of a PlaysTV video page"""

    html = BeautifulSoup(content, "html.parser")
    source_tag = html.find("source", {"res": "720"})

    if not isinstance(source_tag, Tag) or not source_tag.get("src"):
        raise ValueError("Could not find video source with 720p resolution")

    return f"https:{source_tag.get('src')}"


def url_to_filename(url: str) -> str:
    parts = url.split("/")
    return f"{parts[-1]}_{parts[-2]}.mp4"


class DownloadClient:
    """Client for downloading videos from PlaysTV with rate limiting and concurrency control."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rate_limiter: AsyncLimiter,
        semaphore: asyncio.Semaphore,
        save_path: Path,
    ):
        self.session = session
        self.rate_limiter = rate_limiter
        self.semaphore = semaphore
        self.save_path = save_path

    async def download(self, url: str):
        """Download and save a PlaysTV video from a video page URL."""

        path = self.save_path / Path(url_to_filename(url))
        page_content = await self._fetch(url)
        video_url = extract_video_source(page_content)
        await self._download_to_file(video_url, path)

        return path

    async def _fetch(self, url: str) -> bytes:
        """Fetch content from a URL"""

        async with self.semaphore:
            await self.rate_limiter.acquire()

            async with self.session.get(url) as response:
                response.raise_for_status()
                return await response.read()

    async def _download_to_file(self, url: str, path: Path) -> None:
        """Download content from a URL to a file"""

        async with self.semaphore:
            await self.rate_limiter.acquire()
            async with self.session.get(url) as response:
                response.raise_for_status()

                async with aiofiles.open(path, "wb") as f:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        await f.write(chunk)
