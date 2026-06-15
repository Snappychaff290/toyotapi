"""Placeholder screens for modules that arrive in later phases."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from .base import FrameScreen


class PlaceholderScreen(FrameScreen):
    def __init__(self, title: str, glyph: str, phase: int,
                 description: str, nav_key: str) -> None:
        super().__init__()
        self.TITLE_TEXT = title
        self.NAV_KEY = nav_key
        self._glyph = glyph
        self._phase = phase
        self._description = description

    def compose_body(self) -> ComposeResult:
        with Container(id="placeholder-center"):
            box = Container(id="placeholder-box", classes="panel")
            box.border_title = "MODULE STATUS"
            box.border_subtitle = f"PHASE {self._phase}"
            with box:
                yield Static(
                    f"\n[bold]{self._glyph}[/bold]\n\n"
                    f"[bold]{self.TITLE_TEXT}[/bold] — OFFLINE\n\n"
                    f"[#008f25]{self._description}[/]\n\n"
                    f"[#006618]HARDWARE + SOFTWARE ARRIVE IN "
                    f"PHASE {self._phase}[/]\n",
                    id="placeholder-text",
                )
