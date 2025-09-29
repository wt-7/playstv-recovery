from pathlib import Path
from typing import Set
import asyncio
import aiofiles


class Cache:
    def __init__(self, path: Path):
        self._exclusion_list_path = path
        self._excluded_urls: Set[str] = set()
        self._lock = asyncio.Lock()

        self._exclusion_list_path.parent.mkdir(parents=True, exist_ok=True)
        self._exclusion_list_path.touch(exist_ok=True)
        self._excluded_urls = set(self._exclusion_list_path.read_text().splitlines())

    async def add(self, url: str) -> None:
        """Add a URL to the exclusion list."""
        async with self._lock:
            if url not in self._excluded_urls:
                async with aiofiles.open(self._exclusion_list_path, "a") as f:
                    await f.write(f"{url}\n")
                self._excluded_urls.add(url)

    def __contains__(self, url: str) -> bool:
        """Check if a URL is in the exclusion list."""
        return url in self._excluded_urls
