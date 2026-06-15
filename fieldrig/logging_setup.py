"""Per-module file logging under /var/log/fieldrig (or local fallback).

boot.log gets everything, errors.log gets WARNING+, and each hardware
module gets its own file (audio.log, gps.log, ...) via get_module_logger.
Nothing goes to stdout -- the terminal belongs to the TUI.
"""

import logging

from .config import log_dir

_FMT = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
_configured = False
_module_files: set[str] = set()


def setup_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("fieldrig")
    root.setLevel(level)
    root.propagate = False

    boot = logging.FileHandler(log_dir() / "boot.log")
    boot.setFormatter(_FMT)
    root.addHandler(boot)

    errors = logging.FileHandler(log_dir() / "errors.log")
    errors.setLevel(logging.WARNING)
    errors.setFormatter(_FMT)
    root.addHandler(errors)

    _configured = True


def get_module_logger(name: str) -> logging.Logger:
    """Logger that also writes to its own <name>.log file."""
    setup_logging()
    logger = logging.getLogger(f"fieldrig.{name}")
    if name not in _module_files:
        handler = logging.FileHandler(log_dir() / f"{name}.log")
        handler.setFormatter(_FMT)
        logger.addHandler(handler)
        _module_files.add(name)
    return logger
