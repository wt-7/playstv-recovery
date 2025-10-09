import asyncio
import collections
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from playstv_recovery.console import console


@dataclass
class StatsEvent:
    message: str
    timestamp: datetime = field(default_factory=datetime.now)

    def time(self) -> str:
        return self.timestamp.strftime("%H:%M:%S")


@dataclass
class DownloadStats:
    """Thread-safe statistics tracker for download progress."""

    total: int = 0
    found: int = 0
    completed: int = 0
    skipped: int = 0
    failed: int = 0

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _event_feed: collections.deque[StatsEvent] = field(
        default_factory=lambda: collections.deque(maxlen=5), repr=False
    )
    _update_callback: Optional[Callable[[], None]] = field(default=None, repr=False)

    @property
    def remaining(self) -> int:
        """Calculate remaining videos to download."""
        return max(self.found - self.completed - self.skipped - self.failed, 0)

    async def increment_found(self) -> None:
        async with self._lock:
            self.found += 1
            self._notify()

    async def increment_completed(self, name: str) -> None:
        async with self._lock:
            self.completed += 1
            self._event_feed.appendleft(StatsEvent(name))
            self._notify()

    async def increment_skipped(self) -> None:
        async with self._lock:
            self.skipped += 1
            self._notify()

    async def increment_failed(self) -> None:
        # TODO: take the error message as argument
        async with self._lock:
            self.failed += 1
            self._notify()

    async def set_total(self, total: int) -> None:
        async with self._lock:
            self.total = total
            self._notify()

    def set_update_callback(self, callback: Optional[Callable[[], None]]) -> None:
        """Set a callback to be invoked when stats are updated."""
        self._update_callback = callback

    def _notify(self) -> None:
        """Notify callback of stats update."""
        if self._update_callback:
            self._update_callback()


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
        table.add_row(
            "Listed video count:", f"[magenta]{self.stats.total or "~"}[/magenta]"
        )
        table.add_row("Videos found:", f"[cyan]{self.stats.found}[/cyan]")
        table.add_row("Downloads completed:", f"[green]{self.stats.completed}[/green]")
        table.add_row("Downloads skipped:", f"[dim]{self.stats.skipped}[/dim]")
        table.add_row("Downloads failed:", f"[red]{self.stats.failed}[/red]")
        table.add_row(
            "Downloads remaining:", f"[yellow]{self.stats.remaining}[/yellow]"
        )

        if self.stats._event_feed:
            table.add_row("[bold]Recent Downloads:[/bold]", "")
            for event in self.stats._event_feed:
                table.add_row("", f"{event.time()}: [white]{event.message}[/white]")

        return Panel(table, border_style="bold blue")


def print_report(stats: DownloadStats) -> None:
    """Print a comprehensive report of download statistics."""
    console.print("\n[bold]Download Summary[/bold]")
    console.print("=" * 50)

    # Overview statistics
    console.print(f"\nTotal videos listed: {stats.total}")
    console.print(f"Videos found: {stats.found}")
    console.print(f"Successfully downloaded: [green]{stats.completed}[/green]")
    console.print(f"Skipped (already exist): [dim]{stats.skipped}[/dim]")
    console.print(f"Failed: [red]{stats.failed}[/red]")

    # Calculate derived metrics
    processed = stats.completed + stats.skipped + stats.failed
    success_rate = (stats.completed / stats.found * 100) if stats.found > 0 else 0

    # Status determination
    console.print("\n[bold]Status:[/bold]")

    # Check for scraper issues first (most critical)
    if stats.found < stats.total:
        missing = stats.total - stats.found
        console.print(
            f"[bold yellow]⚠ Warning:[/bold yellow] Scraper only found {stats.found}/{stats.total} videos "
            f"({missing} missing). Some videos may not have been discovered."
        )

    # Check download completion
    if stats.failed == 0 and processed == stats.found:
        if stats.completed == stats.found:
            console.print(
                f"[bold green]✓ Complete:[/bold green] All {stats.found} videos downloaded successfully."
            )
        else:
            console.print(
                f"[bold green]✓ Complete:[/bold green] All {stats.found} videos processed "
                f"({stats.completed} downloaded, {stats.skipped} already existed)."
            )
    elif stats.failed > 0:
        console.print(
            f"[bold red]✗ Incomplete:[/bold red] {stats.failed} download(s) failed. "
            f"Success rate: {success_rate:.1f}%"
        )

    console.rule()
