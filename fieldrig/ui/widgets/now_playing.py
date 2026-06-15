"""Now-playing readout: title, artist · album, transport + progress."""

from textual.widgets import Static

from ...config import PROGRESS_WIDTH

STATUS_ICONS = {"Playing": "▶", "Paused": "⏸", "Stopped": "⏹"}


def _fmt_time(microseconds) -> str:
    if not isinstance(microseconds, int) or microseconds < 0:
        return "--:--"
    seconds = microseconds // 1_000_000
    return f"{seconds // 60}:{seconds % 60:02d}"


class NowPlaying(Static):
    def on_mount(self) -> None:
        self._unsub = self.app.bus.subscribe("audio_update", self._on_audio)
        self._on_audio("audio_update", getattr(self.app, "audio_state", {}))

    def on_unmount(self) -> None:
        self._unsub()

    def _on_audio(self, event: str, state) -> None:
        state = state or {}
        title = state.get("title") or ""
        artist = state.get("artist") or ""
        album = state.get("album") or ""

        if title:
            line1 = f"[bold]{title}[/bold]"
            line2 = f"[#008f25]{artist or 'UNKNOWN ARTIST'}"
            if album:
                line2 += f"  ·  {album}"
            line2 += "[/]"
        else:
            line1 = "[#008f25]NO MEDIA[/]"
            line2 = "[#006618]pair a phone or start a player[/]"

        icon = STATUS_ICONS.get(state.get("status", "Stopped"), "⏹")
        position, length = state.get("position"), state.get("length")
        if isinstance(position, int) and isinstance(length, int) and length > 0:
            filled = round(PROGRESS_WIDTH * min(1.0, position / length))
            bar = "═" * filled + "┄" * (PROGRESS_WIDTH - filled)
            timing = f"[#008f25]{_fmt_time(position)} / {_fmt_time(length)}[/]"
        else:
            bar = "┄" * PROGRESS_WIDTH
            timing = ""

        self.update(f"{line1}\n{line2}\n{icon}  ╞{bar}╡  {timing}")
