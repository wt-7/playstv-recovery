from pathlib import Path
from typing import Set
import asyncio
import aiofiles

HEADER = """# This is a cache file for playstv-recovery. Video URLs that are on this list will not be re-downloaded.
# Freely delete this file or remove entries to re-download videos.\n"""


class Cache:
    """
    A persistent, async-safe cache for tracking downloaded video URLs.

    The cache maintains an in-memory set for fast lookups and persists
    URLs to disk for durability across sessions.
    """

    def __init__(self, cache_path: Path):
        self.path = cache_path
        self._urls: Set[str] = set()
        self._lock = asyncio.Lock()
        self._initialize_cache()

    def _initialize_cache(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        if not self.path.exists():
            self.path.write_text(HEADER)
        else:
            self._urls = self._load_urls()

    def _load_urls(self) -> Set[str]:
        return {
            line.strip()
            for line in self.path.read_text().splitlines()
            if line.strip() and not line.startswith("#")
        }

    async def add(self, url: str) -> bool:
        async with self._lock:
            if url in self._urls:
                return False

            async with aiofiles.open(self.path, "a") as f:
                await f.write(f"{url}\n")

            self._urls.add(url)
            return True

    def __contains__(self, url: str) -> bool:
        return url in self._urls
