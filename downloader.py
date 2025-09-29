import asyncio
from pathlib import Path
import aiofiles
import aiohttp
from bs4 import BeautifulSoup, Tag
from aiolimiter import AsyncLimiter

CHUNK_SIZE = 8192


def extract_video_source(content: bytes):
    html = BeautifulSoup(content, "html.parser")
    source_tag = html.find("source", {"res": "720"})

    if not isinstance(source_tag, Tag) or not source_tag.get("src"):
        raise ValueError("Could not find video source with 720p resolution")

    return f"https:{source_tag.get('src')}"


class DownloadClient:
    """Handles HTTP requests with rate limiting and concurrency control."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rate_limiter: AsyncLimiter,
        semaphore: asyncio.Semaphore,
        path: Path,
    ):
        self.session = session
        self.rate_limiter = rate_limiter
        self.semaphore = semaphore
        self.path = path

    async def download(self, url: str):
        save_path = self.path / Path(f"{url.split("/")[-1]}.mp4")
        page_content = await self._fetch(url)
        video_url = extract_video_source(page_content)
        await self._download_to_file(video_url, save_path)

        return save_path

    async def _fetch(self, url: str) -> bytes:
        """Fetch content from URL with rate limiting and concurrency control."""

        async with self.semaphore:
            await self.rate_limiter.acquire()

            async with self.session.get(url) as response:
                response.raise_for_status()
                return await response.read()

    async def _download_to_file(self, url: str, path: Path) -> None:
        """Download content from URL to file with rate limiting and concurrency control."""

        async with self.semaphore:
            await self.rate_limiter.acquire()
            async with self.session.get(url) as response:
                response.raise_for_status()

                async with aiofiles.open(path, "wb") as f:
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        await f.write(chunk)
