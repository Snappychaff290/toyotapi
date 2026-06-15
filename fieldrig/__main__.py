"""FieldRig entry point.

    python -m fieldrig            run the server (Chromium kiosk UI)
    python -m fieldrig --tui      Textual debug console (e.g. over SSH)
    python -m fieldrig --check    start modules headless, print status, exit
"""

import argparse
import asyncio
import sys

from . import __version__


async def _check() -> int:
    from .core import EventBus, ModuleManager
    from .logging_setup import setup_logging
    from .modules.audio import AudioModule

    setup_logging()
    bus = EventBus()
    bus.attach_loop(asyncio.get_running_loop())
    manager = ModuleManager(bus)
    manager.register(AudioModule(bus))

    await manager.start_all()
    await asyncio.sleep(0.5)
    failures = 0
    for name, status in (await manager.statuses()).items():
        running = status.pop("running")
        mark = "OK " if running else "FAIL"
        if not running:
            failures += 1
        print(f"[{mark}] {name}: {status}")
    await manager.stop_all()
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="fieldrig",
                                     description="FieldRig vehicle terminal")
    parser.add_argument("--check", action="store_true",
                        help="start modules headless, print status, exit")
    parser.add_argument("--tui", action="store_true",
                        help="run the Textual debug console instead of the server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--version", action="version",
                        version=f"fieldrig {__version__}")
    args = parser.parse_args()

    if args.check:
        sys.exit(asyncio.run(_check()))

    if args.tui:
        from .ui.app import FieldRigApp
        FieldRigApp().run()
        return

    import uvicorn
    from .server import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
