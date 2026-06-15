"""Unicode block-bar waveform, two rows tall for double the vertical
resolution. Fed by waveform_update events from the analyzer."""

from textual.widgets import Static

BLOCKS = "▁▂▃▄▅▆▇█"  # 1..8 eighths


class WaveformDisplay(Static):
    def __init__(self, rows: int = 2, **kwargs) -> None:
        super().__init__(**kwargs)
        self._rows = max(1, rows)

    def on_mount(self) -> None:
        self._unsub = self.app.bus.subscribe("waveform_update", self._on_wave)

    def on_unmount(self) -> None:
        self._unsub()

    def _on_wave(self, event: str, levels) -> None:
        if self._rows == 1:
            self.update("".join(
                BLOCKS[min(7, int(level * 8))] for level in levels
            ))
            return
        top: list[str] = []
        bottom: list[str] = []
        for level in levels:
            units = max(1, min(16, round(level * 16)))
            if units <= 8:
                top.append(" ")
                bottom.append(BLOCKS[units - 1])
            else:
                top.append(BLOCKS[units - 9])
                bottom.append(BLOCKS[7])
        self.update("".join(top) + "\n" + "".join(bottom))
