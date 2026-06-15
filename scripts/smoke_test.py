"""Automated UI smoke test using Textual's test pilot.

Boots the app headless, exercises navigation and the audio controls,
and verifies the event bus is feeding the UI. Run with:
    .venv/bin/python scripts/smoke_test.py
"""

import asyncio
import sys

from fieldrig.ui.app import FieldRigApp
from fieldrig.ui.screens import (
    AudioScreen,
    BluetoothScreen,
    HomeScreen,
    PlaceholderScreen,
)
from fieldrig.ui.widgets import WaveformDisplay


async def main() -> None:
    app = FieldRigApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen), app.screen

        # Event bus -> UI: waveform simulation should be painting bars.
        await asyncio.sleep(0.5)
        await pilot.pause()
        waveform = app.screen.query_one(WaveformDisplay)
        assert str(waveform.content).strip(), "waveform never updated"

        # Tab navigation.
        await pilot.click("#nav-audio")
        await pilot.pause()
        assert isinstance(app.screen, AudioScreen), app.screen

        # Audio controls dispatch without blowing up (no hardware here).
        for control in ("#ctl-play", "#ctl-volup", "#ctl-voldown"):
            await pilot.click(control)
        await pilot.pause()

        # Bluetooth management screen.
        await pilot.click("#ctl-bt")
        await pilot.pause()
        assert isinstance(app.screen, BluetoothScreen), app.screen
        await pilot.click("#nav-back")
        await pilot.pause()
        assert isinstance(app.screen, AudioScreen), app.screen

        # Placeholder tab + back home via nav.
        await pilot.click("#nav-radio")
        await pilot.pause()
        assert isinstance(app.screen, PlaceholderScreen), app.screen
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, HomeScreen), app.screen

        # Module manager state.
        statuses = await app.manager.statuses()
        assert statuses["audio"]["running"], statuses

    print("SMOKE TEST PASSED")
    print(f"  audio status: {statuses['audio']}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as exc:
        print(f"SMOKE TEST FAILED: {exc!r}")
        sys.exit(1)
