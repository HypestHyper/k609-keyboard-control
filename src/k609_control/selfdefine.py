"""Self define: a colour for every key.

Decoded on 2026-11-06 from a recording of the official software painting Esc red, A green, Space blue
and Right white on an all-black layout:
- The table saved with 06 09 cc starts with three 126-byte planes, red, green and blue, after its
  8-byte header. A key's byte in each plane is its colour index (the second number of its entry in
  the official software's Cfg.ini): Esc = 21 -> byte 29 red; A = 64 -> byte 198 green (8 + 126 + 64).
- The rest of that table, and the whole 06 09 d0 table, never changed; they're sent as recorded.
- Saving: read the lighting block, 20 ms, colour table, 50 ms, second table, 50 ms, lighting block
  with the effect set to Self define. The colours can't be read back, so the app keeps its own copy.
"""

from __future__ import annotations

import json
import os

from . import capabilities, lighting
from .hidraw import BLOCK_BUFFER_LEN, Session
from .settings import atomic_write_json, config_dir

PLANE = 126
PLANES_END = 8 + 3 * PLANE
HERE = os.path.dirname(os.path.abspath(__file__))

# key number (keymap.Key.number / keymap.LAYOUT) -> colour index in the planes, from Cfg.ini
COLOUR_INDEX = {
    1: 21, 7: 22, 13: 23, 19: 24, 25: 25, 31: 26, 37: 27, 43: 28, 49: 29, 55: 30, 61: 31, 67: 32,
    73: 33, 79: 34, 91: 36, 93: 78, 2: 42, 8: 43, 14: 44, 20: 45, 26: 46, 32: 47, 38: 48, 44: 49,
    50: 50, 56: 51, 62: 52, 68: 53, 74: 54, 80: 55, 92: 57, 94: 99, 3: 63, 9: 64, 15: 65, 21: 66,
    27: 67, 33: 68, 39: 69, 45: 70, 51: 71, 57: 72, 63: 73, 69: 74, 81: 76, 4: 84, 10: 86, 16: 87,
    22: 88, 28: 89, 34: 90, 40: 91, 46: 92, 52: 93, 58: 94, 64: 95, 82: 97, 88: 98, 5: 105, 11: 106,
    17: 107, 35: 110, 53: 113, 59: 114, 65: 115, 83: 118, 89: 119, 95: 120,
}
GAP_BEFORE_TABLES = 0.02
GAP_BETWEEN = 0.05

_templates: dict[str, bytes] = {}


def template(name: str) -> bytes:
    """The table as the official software sent it (colour planes all zero)."""
    if name not in _templates:
        with open(os.path.join(HERE, f"selfdefine_{name}.hex"), encoding="ascii") as f:
            data = bytes.fromhex(f.read().strip())
        _templates[name] = data + bytes(BLOCK_BUFFER_LEN - len(data))
    return _templates[name]


def build_colour_table(colours: dict[int, tuple[int, int, int]]) -> bytes:
    """colours: key number -> (r, g, b); keys not given are black."""
    t = bytearray(template("cc"))
    for number, rgb in colours.items():
        if number not in COLOUR_INDEX:
            raise ValueError(f"no colour index for key {number}")
        if len(rgb) != 3 or any(not 0 <= c <= 255 for c in rgb):
            raise ValueError("colour out of range")
        for plane, value in enumerate(rgb):
            t[8 + plane * PLANE + COLOUR_INDEX[number]] = value
    return bytes(t)


def is_colour_table_write(buf: bytes) -> bool:
    t = template("cc")
    return len(buf) == BLOCK_BUFFER_LEN and buf[:8] == t[:8] and buf[PLANES_END:] == t[PLANES_END:]


def is_second_table_write(buf: bytes) -> bool:
    return bytes(buf) == template("d0")


def apply(devnode: str, colours: dict[int, tuple[int, int, int]], **io) -> lighting.State:
    """Send the per-key colours and switch the effect to Self define, as the official software does."""
    capabilities.require_usable("lighting")
    capabilities.require_usable("selfdefine")
    table = build_colour_table(colours)
    with Session(devnode, **io) as s:
        res = s.read_lighting()
        if not res.ok:
            raise lighting.UnexpectedBlock(res.problem)
        block = res.data
        lighting.parse(block)
        s.pause(GAP_BEFORE_TABLES)
        s.write_selfdefine(table, template("d0"))
        s.pause(GAP_BETWEEN)
        s.write_lighting(lighting.build_write(block, effect=lighting.SELF_DEFINE))
        s.pause(0.04)
        after = s.read_lighting()
    if not after.ok:
        raise lighting.VerifyFailed(after.problem)
    st = lighting.parse(after.data)
    if st.effect != lighting.SELF_DEFINE:
        raise lighting.VerifyFailed("The keyboard didn't switch to Self define.")
    return st


# --- the app's copy (the keyboard can't report it) ---------------------------------

def store_path() -> str:
    return os.path.join(config_dir(), "selfdefine.json")


def to_json(colours: dict[int, tuple[int, int, int]]) -> dict:
    return {str(n): "".join(f"{c:02x}" for c in rgb) for n, rgb in colours.items() if any(rgb)}


def from_json(data) -> dict[int, tuple[int, int, int]]:
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                n = int(k)
                rgb = tuple(bytes.fromhex(v))
            except (ValueError, TypeError):
                continue
            if n in COLOUR_INDEX and len(rgb) == 3:
                out[n] = rgb
    return out


def load(path: str | None = None) -> dict[int, tuple[int, int, int]]:
    try:
        with open(path or store_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return from_json(data.get("colours") if isinstance(data, dict) and data.get("version") == 1 else None)


def save(colours: dict[int, tuple[int, int, int]], path: str | None = None) -> None:
    atomic_write_json(path or store_path(), {"version": 1, "colours": to_json(colours)})
