"""K609GG macros on normal keys.

Decoded on 2026-11-06 from four macros saved by the official software:
- The macro block (saved with 06 05 e8 00 40 00 00 00) holds 128-byte slots, slot 0 first.
- A slot is: 00, repeat count, then 2-byte events [timing, key]. Bit 0x80 of timing marks a key
  release; its low 7 bits are the pause after the event in ms (1-127). A longer pause is written
  as 03 in the event, followed by 00 03 and a 2-byte count of 100 ms steps.
- A key that plays a macro has key map entry 10 00 <mode> <0x18 + slot>; mode 01 repeats it the
  slot's count of times, 04 repeats it while the key is held.
- Saving: read the key map, write the macro block, then write the key map.
The keyboard has no known way to report macros back, so Horus Control keeps its own copy.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from . import capabilities, keymap
from .hidraw import BLOCK_BUFFER_LEN, MACRO_WRITE_HEADER, Session
from .settings import atomic_write_json, config_dir

SLOT_LEN = 128
SLOTS = (BLOCK_BUFFER_LEN - 8) // SLOT_LEN          # 8
MAX_EVENTS = (SLOT_LEN - 2) // 2 - 2                 # leave room for one long pause
MACRO_TYPE = 0x10
SLOT_BASE = 0x18
MODE_TIMES = 0x01
MODE_HELD = 0x04
SHORT_MAX = 127                                       # ms that fit in an event
LONG_STEP = 100                                       # ms per step of a long pause
LONG_MAX = 60_000
MIN_TIMING = 0x03                                     # what the official software writes for "no short pause"
SAVE_GAP = 0.03
TABLE_GAP = 0.05


@dataclass
class Step:
    key: int          # USB key code (keymap.TARGETS)
    down: bool        # True = press, False = release
    pause: int = 0    # ms after this step

    def to_dict(self):
        return {"key": self.key, "down": self.down, "pause": self.pause}


@dataclass
class Macro:
    name: str
    steps: list[Step] = field(default_factory=list)
    held: bool = False         # True: repeat while the key is held; False: repeat `count` times
    count: int = 1
    key: str | None = None     # key the macro is assigned to (keymap key name)

    def to_dict(self):
        return {"name": self.name, "steps": [s.to_dict() for s in self.steps], "held": self.held,
                "count": self.count, "key": self.key}


def check_pause(ms: int) -> int:
    """Pauses are either 0-127 ms, or whole multiples of 100 ms up to 60 s."""
    if not isinstance(ms, int) or ms < 0:
        raise ValueError("Pauses can't be negative.")
    if ms <= SHORT_MAX:
        return ms
    if ms % LONG_STEP or ms > LONG_MAX:
        raise ValueError("Pauses over 127 ms must be whole multiples of 100 ms, up to 60 seconds.")
    return ms


def validate(m: Macro) -> None:
    if not m.name.strip():
        raise ValueError("Give the macro a name.")
    if not m.steps:
        raise ValueError("Add at least one step.")
    if not 1 <= m.count <= 255:
        raise ValueError("Repeat count must be between 1 and 255.")
    for s in m.steps:
        if s.key not in keymap.TARGETS:
            raise ValueError("Unsupported key in a step.")
        check_pause(s.pause)
    if len(encode_events(m.steps)) > SLOT_LEN - 2:
        raise ValueError("The macro is too long for one slot. Remove some steps or long pauses.")


def encode_events(steps: list[Step]) -> bytes:
    out = bytearray()
    for s in steps:
        flag = 0x00 if s.down else 0x80
        pause = check_pause(s.pause)
        if 1 <= pause <= SHORT_MAX:
            out += bytes([flag | pause, s.key])
        else:
            out += bytes([flag | MIN_TIMING, s.key])
            if pause:
                n = pause // LONG_STEP
                out += bytes([0x00, 0x03, n >> 8, n & 0xFF])
    return bytes(out)


def encode_slot(m: Macro) -> bytes:
    validate(m)
    data = bytes([0x00, m.count]) + encode_events(m.steps)
    return data + bytes(SLOT_LEN - len(data))


def build_block(macros: list[Macro]) -> bytes:
    if len(macros) > SLOTS:
        raise ValueError(f"The keyboard holds up to {SLOTS} assigned macros.")
    body = b"".join(encode_slot(m) for m in macros)
    return MACRO_WRITE_HEADER + body + bytes(BLOCK_BUFFER_LEN - 8 - len(body))


def key_entry(m: Macro, slot: int) -> bytes:
    return bytes([MACRO_TYPE, 0x00, MODE_HELD if m.held else MODE_TIMES, SLOT_BASE + slot])


# --- storage ---------------------------------------------------------------------

def store_path() -> str:
    return os.path.join(config_dir(), "macros.json")


def load(path: str | None = None) -> list[Macro]:
    path = path or store_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    if not isinstance(data, dict) or data.get("version") != 1:
        return []
    names = {k.name for k in keymap.REMAPPABLE}
    for item in data.get("macros", []):
        try:
            m = Macro(str(item["name"]),
                      [Step(int(s["key"]), bool(s["down"]), int(s["pause"])) for s in item["steps"]],
                      bool(item.get("held", False)), int(item.get("count", 1)),
                      item.get("key") if item.get("key") in names else None)
            validate(m)
            out.append(m)
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save(macros: list[Macro], path: str | None = None) -> None:
    atomic_write_json(path or store_path(), {"version": 1, "macros": [m.to_dict() for m in macros]})


# --- device ------------------------------------------------------------------------

def apply(devnode: str, macros: list[Macro], **io) -> dict[str, int]:
    """Write all assigned macros and point their keys at them, as the official software does.

    Keys that play a macro not in `macros` (for example one set by the official software) are reset
    to their default, because their slot is overwritten.
    """
    capabilities.require_usable("macros")
    assigned = [m for m in macros if m.key]
    keys = [m.key for m in assigned]
    if len(set(keys)) != len(keys):
        raise ValueError("Two macros are assigned to the same key.")
    block = build_block(assigned)
    by_name = {k.name: k for k in keymap.REMAPPABLE}
    with Session(devnode, **io) as s:
        res = s.read_keymap()
        if not res.ok:
            raise keymap.UnexpectedKeymap(res.problem)
        keymap.check(res.data)
        out = bytearray(keymap.WRITE_HEADER + res.data[8:BLOCK_BUFFER_LEN])
        for k in keymap.REMAPPABLE:
            off = 8 + 4 * k.entry
            if out[off] == MACRO_TYPE and k.name not in keys:
                out[off:off + 4] = k.special or bytes([keymap.entry_type(k.default), 0, 0, k.default])
        for slot, m in enumerate(assigned):
            off = 8 + 4 * by_name[m.key].entry
            out[off:off + 4] = key_entry(m, slot)
        s.pause(SAVE_GAP)
        s.write_macros(block)
        s.pause(TABLE_GAP)
        s.write_keymap(bytes(out))
        s.pause(SAVE_GAP)
        after = s.read_keymap()
    if not after.ok:
        raise keymap.VerifyFailed(after.problem)
    e = keymap.entries(after.data)
    for slot, m in enumerate(assigned):
        if e[by_name[m.key].entry] != key_entry(m, slot):
            raise keymap.VerifyFailed("The keyboard didn't keep the macro assignment.")
    return keymap.current(after.data)
