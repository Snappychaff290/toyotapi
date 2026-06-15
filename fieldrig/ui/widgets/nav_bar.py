"""Bottom navigation rail. The current tab is highlighted; presses
bubble up to the app, which owns the screen stack."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button

NAV_ITEMS = [
    ("home", "⌂"),
    ("audio", "♪ AUDIO"),
    ("nav", "◈ NAV"),
    ("obd", "▣ OBD"),
    ("radio", "≋ RADIO"),
    ("mesh", "✉ MESH"),
    ("camera", "◉ CAM"),
    ("system", "⚙ SYS"),
]


class NavBar(Horizontal):
    def __init__(self, current: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._current = current

    def compose(self) -> ComposeResult:
        for key, label in NAV_ITEMS:
            classes = "-current" if key == self._current else ""
            yield Button(label, id=f"nav-{key}", classes=classes)
