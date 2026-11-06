"""K609GG lighting: effect, brightness and speed.

Decoded on 2026-11-06 from the lighting block, by changing one setting at a time in the
official software and reading the block back (see README). Colour is not in this block.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

from . import capabilities
from .hidraw import BLOCK_BUFFER_LEN, BLOCK_LEN, LIGHTING_REPLY_PREFIX, Session
from .settings import atomic_write_json, config_dir

CUSTOM_BYTE = 20
EFFECT_BYTE = 21
SELF_DEFINE = 0x15
MAX_LEVEL = 4

EFFECTS: dict[int, str] = {
    0x00: "Off", 0x01: "Fixed on", 0x02: "Respire", 0x03: "Rainbow", 0x04: "Flash away",
    0x05: "Raindrops", 0x06: "Rainbow wheel", 0x07: "Ripples shining", 0x08: "Stars twinkle",
    0x09: "Shadow disappear", 0x0A: "Retro snake", 0x0B: "Neon stream", 0x0C: "Reaction",
    0x0D: "Sine wave", 0x0E: "Retinue scanning", 0x0F: "Rotating windmill",
    0x10: "Colour waterfall", 0x11: "Blossoming", 0x12: "Rotating storm", SELF_DEFINE: "Self define",
}
LEVEL_EFFECTS = range(0x01, 0x13)     # effects with their own brightness/speed byte


class UnexpectedBlock(ValueError):
    """The keyboard's block doesn't look like the layout decoded for this keyboard."""


class VerifyFailed(RuntimeError):
    pass


def level_offset(effect: int) -> int | None:
    """Byte holding speed (high digit) and brightness (low digit) for one effect."""
    return 39 + 2 * (effect - 1) if effect in LEVEL_EFFECTS else None


@dataclass(frozen=True)
class State:
    effect: int
    brightness: int | None
    speed: int | None
    levels: dict[int, int]            # effect -> raw level byte, for every LEVEL_EFFECTS entry

    @property
    def name(self) -> str:
        return EFFECTS[self.effect]


def parse(block: bytes) -> State:
    if len(block) < BLOCK_LEN or not block.startswith(LIGHTING_REPLY_PREFIX) or block[14:16] != b"\x5a\xa5":
        raise UnexpectedBlock("The lighting block has an unexpected header.")
    effect = block[EFFECT_BYTE]
    if effect not in EFFECTS:
        raise UnexpectedBlock(f"Unknown effect number 0x{effect:02x}.")
    if block[CUSTOM_BYTE] != (1 if effect == SELF_DEFINE else 0):
        raise UnexpectedBlock(f"Unexpected value 0x{block[CUSTOM_BYTE]:02x} in byte 20.")
    levels = {}
    for e in LEVEL_EFFECTS:
        v = block[level_offset(e)]
        if v >> 4 > MAX_LEVEL or v & 0xF > MAX_LEVEL:
            raise UnexpectedBlock(f"Unexpected speed/brightness byte 0x{v:02x} for {EFFECTS[e]}.")
        levels[e] = v
    v = levels.get(effect)
    return State(effect, None if v is None else v & 0xF, None if v is None else v >> 4, levels)


def build_write(block: bytes, *, effect: int | None = None, brightness: int | None = None,
                speed: int | None = None, levels: dict[int, int] | None = None) -> bytes:
    """The block as read, with only known fields changed, shaped as a save (06 03 c6 …)."""
    parse(block)
    b = bytearray(block[:BLOCK_LEN])
    b[1] = 0x03
    if effect is not None:
        if effect not in EFFECTS:
            raise ValueError("unknown effect")
        b[EFFECT_BYTE] = effect
        b[CUSTOM_BYTE] = 1 if effect == SELF_DEFINE else 0
    for e, v in (levels or {}).items():
        if e not in LEVEL_EFFECTS or v >> 4 > MAX_LEVEL or v & 0xF > MAX_LEVEL:
            raise ValueError("bad level")
        b[level_offset(e)] = v
    if brightness is not None or speed is not None:
        off = level_offset(b[EFFECT_BYTE])
        if off is None:
            raise ValueError(f"{EFFECTS[b[EFFECT_BYTE]]} has no brightness or speed setting")
        for v in (brightness, speed):
            if v is not None and not 0 <= v <= MAX_LEVEL:
                raise ValueError("level out of range")
        cur = b[off]
        b[off] = ((cur >> 4 if speed is None else speed) << 4) | (cur & 0xF if brightness is None else brightness)
    return bytes(b) + bytes(BLOCK_BUFFER_LEN - BLOCK_LEN)


def _known_fields(block: bytes) -> tuple:
    return (block[CUSTOM_BYTE], block[EFFECT_BYTE], tuple(block[level_offset(e)] for e in LEVEL_EFFECTS))


# --- backup: known values only, never raw bytes ---------------------------------

def backup_path() -> str:
    return os.path.join(config_dir(), "lighting-backup.json")


def save_backup(state: State, path: str) -> None:
    atomic_write_json(path, {"version": 1, "saved": datetime.now().isoformat(timespec="seconds"),
                             "effect": state.effect,
                             "levels": {f"{e:02x}": v for e, v in state.levels.items()}})


def load_backup(path: str) -> tuple[str, int, dict[int, int]] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != 1 or data.get("effect") not in EFFECTS:
            return None
        levels = {int(k, 16): int(v) for k, v in data["levels"].items()}
        if set(levels) != set(LEVEL_EFFECTS) or any(v >> 4 > MAX_LEVEL or v & 0xF > MAX_LEVEL or v < 0
                                                    for v in levels.values()):
            return None
        return str(data.get("saved", "")), data["effect"], levels
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


# --- device operations ------------------------------------------------------------

def _read(session: Session) -> bytes:
    res = session.read_lighting()
    if not res.ok:
        raise UnexpectedBlock(res.problem)
    return res.data


def read_state(devnode: str, **io) -> State:
    with Session(devnode, **io) as s:
        return parse(_read(s))


def apply(devnode: str, *, backup: str | None = None, **change) -> State:
    """Read, change only the requested known fields, save, then read back and check."""
    capabilities.require_usable("lighting")
    io = {k: change.pop(k) for k in ("opener", "ioctl", "closer", "sleep") if k in change}
    with Session(devnode, **io) as s:
        block = _read(s)
        before = parse(block)
        if backup and not os.path.exists(backup):
            save_backup(before, backup)
        payload = build_write(block, **change)
        if payload[:BLOCK_LEN][3:] == block[3:BLOCK_LEN]:
            return before
        s.write_lighting(payload)
        after = _read(s)
    if _known_fields(after) != _known_fields(payload):
        raise VerifyFailed("The keyboard didn't keep the change.")
    return parse(after)


def restore(devnode: str, backup: str, **io) -> State:
    saved = load_backup(backup)
    if saved is None:
        raise FileNotFoundError(backup)
    _, effect, levels = saved
    return apply(devnode, effect=effect, levels=levels, **io)
