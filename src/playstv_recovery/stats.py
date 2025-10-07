import asyncio
import collections
from dataclasses import dataclass, field
from typing import Callable, Optional

from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from playstv_recovery.console import console


@dataclass
class DownloadStats:
    """Thread-safe statistics tracker for download progress."""

    found: int = 0
    completed: int = 0
    skipped: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _recent: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=5), repr=False
    )
    _update_callback: Optional[Callable[[], None]] = field(default=None, repr=False)

    @property
    def remaining(self) -> int:
        """Calculate remaining videos to download."""
        return max(self.found - self.completed - self.skipped, 0)

    def set_update_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Set a callback to be invoked when stats are updated."""
        self._update_callback = callback

    def _notify(self) -> None:
        """Notify callback of stats update."""
        if self._update_callback:
            self._update_callback()

    async def increment_found(self) -> None:
        async with self._lock:
            self.found += 1
            self._notify()

    async def increment_completed(self, name: str) -> None:
        async with self._lock:
            self.completed += 1
            self._recent.appendleft(name)
            self._notify()

    async def increment_skipped(self) -> None:
        async with self._lock:
            self.skipped += 1
            self._notify()


class LiveStatsDisplay:
    """Manages the live display of download statistics."""

    def __init__(self, stats: DownloadStats):
        self.stats = stats
        self.live: Live | None = None

    def __enter__(self):
        self.live = Live(self._render(), refresh_per_second=4, console=console)
        self.stats.set_update_callback(self._on_update)
        return self.live.__enter__()

    def __exit__(self, *args):
        # This will not be called, as the __enter__ is delegated to Live's context manager
        # Cleanup will be handled by Live's __exit__
        # This fixes a bug where the table would be constantly re-rendered, leaving artifacts
        pass

    def _on_update(self) -> None:
        """Called when stats are updated."""
        if self.live:
            self.live.update(self._render())
        else:
            raise RuntimeError("Live display not started.")

    def _render(self) -> Panel:
        """Render the stats panel."""
        table = Table(
            title="Download Progress", expand=True, show_header=False, box=None
        )

        table.add_row("Videos Found:", f"[cyan]{self.stats.found}[/cyan]")
        table.add_row("Videos Completed:", f"[green]{self.stats.completed}[/green]")
        table.add_row("Videos Skipped:", f"[dim]{self.stats.skipped}[/dim]")
        table.add_row("Remaining:", f"[yellow]{self.stats.remaining}[/yellow]")

        if self.stats._recent:
            table.add_row("[bold]Recent Downloads:[/bold]", "")
            for name in self.stats._recent:
                table.add_row("", f"[white]{name}[/white]")

        return Panel(table, border_style="bold blue")
