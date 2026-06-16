#!/usr/bin/env python3
"""Generate a fully transparent Xcursor theme.

cage (the kiosk compositor) draws its own mouse pointer parked at screen
centre -- and a touchscreen counts as a pointer device, so it never moves
out of the way. CSS `cursor: none` only hides the cursor over the Chromium
surface, not the compositor's. wlroots has no hide-cursor flag, so the fix is
to make every cursor image transparent and point XCURSOR_THEME at it.

Usage:  make-blank-cursor.py <theme-dir>
e.g.    make-blank-cursor.py ~/.local/share/icons/fieldrig-hidden
"""

import struct
import sys
from pathlib import Path

# Cursor names a compositor / browser might request. They all get the same
# 1x1 transparent image, so whatever is asked for, nothing is drawn.
CURSOR_NAMES = [
    "left_ptr", "default", "arrow", "top_left_arrow", "pointer",
    "hand", "hand1", "hand2", "grab", "grabbing",
    "text", "xterm", "ibeam", "crosshair", "cross",
    "watch", "wait", "progress", "move", "all-scroll",
]

_IMAGE_TYPE = 0xFFFD0002  # Xcursor chunk type for an image


def blank_cursor(size: int = 24) -> bytes:
    """A valid Xcursor file holding one 1x1 fully transparent image."""
    width = height = 1
    pixels = struct.pack("<I", 0x00000000)  # ARGB, fully transparent

    # File header: "Xcur", header size (16), version 1.0, table-of-contents count.
    file_header = b"Xcur" + struct.pack("<III", 16, 0x0001_0000, 1)
    # TOC entry: type, subtype (= nominal size), byte offset of the chunk.
    chunk_offset = len(file_header) + 12
    toc = struct.pack("<III", _IMAGE_TYPE, size, chunk_offset)
    # Image chunk: 36-byte header (9 uint32), then the pixel data.
    chunk = struct.pack(
        "<IIIIIIIII",
        36,            # chunk header size
        _IMAGE_TYPE,   # type
        size,          # subtype (nominal size)
        1,             # image version
        width, height,
        0, 0,          # hotspot x/y
        0,             # delay (ms) -- single, non-animated frame
    ) + pixels
    return file_header + toc + chunk


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    theme_dir = Path(sys.argv[1]).expanduser()
    cursors = theme_dir / "cursors"
    cursors.mkdir(parents=True, exist_ok=True)

    (theme_dir / "index.theme").write_text(
        "[Icon Theme]\n"
        f"Name={theme_dir.name}\n"
        "Comment=Transparent cursor for the FieldRig kiosk\n"
    )
    data = blank_cursor()
    for name in CURSOR_NAMES:
        (cursors / name).write_bytes(data)

    print(f"wrote transparent cursor theme to {theme_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
