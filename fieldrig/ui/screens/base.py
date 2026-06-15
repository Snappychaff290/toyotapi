"""Framed screen base: status bar, titled border frame, nav bar.

Every screen lives inside the same chrome so the whole app reads as
one console: chips strip on top, a bordered body with the screen name
in the frame, and the nav rail on the bottom.
"""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen

from ...config import VERSION
from ..widgets import NavBar, StatusBar


class FrameScreen(Screen):
    TITLE_TEXT = "FIELDRIG"
    NAV_KEY: str | None = None

    def compose_body(self) -> ComposeResult:
        yield from ()

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        body = Container(id="screen-body")
        body.border_title = f"▞▞ FIELDRIG ▸ {self.TITLE_TEXT}"
        body.border_subtitle = f"v{VERSION} ▞▞"
        with body:
            yield from self.compose_body()
        yield NavBar(id="nav-bar", current=self.NAV_KEY)
