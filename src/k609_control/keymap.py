"""K609GG key remapping (normal keys only).

Decoded on 2026-11-06. The key map (read with 05 84 d8, saved with 06 04 d8) is an 8-byte header
and 256 entries of 4 bytes: type, two zero bytes, USB key code. Each key's entry is its key number
from the official software's Cfg.ini; when that entry has type 02 it points elsewhere, and the
key's real entry is its code + 132. This rule places all 66 non-Fn keys at an entry holding their
default code, and matches two remaps recorded from the official software (Caps Lock = 143,
Esc = 147). The entry type follows the key code: 06 for modifiers (e0-e7), 00 for everything
else, as seen when the official software remapped Ctrl, Shift, Win and Alt to letters and back.
Media keys and the Fn keys are left alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import capabilities
from .hidraw import BLOCK_BUFFER_LEN, KEYMAP_REPLY_PREFIX, KEYMAP_WRITE_HEADER as WRITE_HEADER, Session

READ_HEADER = bytes.fromhex("0684d80084000000")
POINTER = 0x02
NORMAL = 0x00
POINTER_BASE = 132
MODIFIER = 0x06
MACRO = 0x10              # entry 10 00 <mode> <0x18 + slot>: the key plays a macro (see macros.py)
MACRO_CODE = 0x100        # current() reports a macro key as MACRO_CODE + slot


def entry_type(code: int) -> int:
    return MODIFIER if 0xE0 <= code <= 0xE7 else NORMAL
SAVE_GAP = 0.03          # the official software saved about 30 ms after reading


@dataclass(frozen=True)
class Key:
    name: str
    number: int          # key number in the official software (Cfg.ini)
    default: int         # USB key code
    entry: int           # entry in the key map, from the rule above
    special: bytes = b""  # the key's own default entry when it isn't a plain code (Right Ctrl)

    @property
    def remappable(self) -> bool:
        return True                      # every key in KEYS; the Fn keys aren't in KEYS


KEYS: tuple[Key, ...] = (
    Key("Esc", 1, 0x29, 147), Key("1", 7, 0x1e, 164), Key("2", 13, 0x1f, 165),
    Key("3", 19, 0x20, 166), Key("4", 25, 0x21, 167), Key("5", 31, 0x22, 168),
    Key("6", 37, 0x23, 169), Key("7", 43, 0x24, 170), Key("8", 49, 0x25, 171),
    Key("9", 55, 0x26, 172), Key("0", 61, 0x27, 173), Key("-", 67, 0x2d, 174),
    Key("=", 73, 0x2e, 175), Key("Backspace", 79, 0x2a, 158), Key("Delete", 91, 0x4c, 91),
    Key("Page Up", 93, 0x4b, 93), Key("Tab", 2, 0x2b, 176), Key("Q", 8, 0x14, 177),
    Key("W", 14, 0x1a, 160), Key("E", 20, 0x08, 178), Key("R", 26, 0x15, 179),
    Key("T", 32, 0x17, 137), Key("Y", 38, 0x1c, 38), Key("U", 44, 0x18, 44),
    Key("I", 50, 0x0c, 50), Key("O", 56, 0x12, 56), Key("P", 62, 0x13, 62),
    Key("[", 68, 0x2f, 132), Key("]", 74, 0x30, 133), Key("\\", 80, 0x31, 159),
    Key("`", 92, 0x35, 92), Key("Page Down", 94, 0x4e, 94), Key("Caps Lock", 3, 0x39, 143),
    Key("A", 9, 0x04, 9), Key("S", 15, 0x16, 15), Key("D", 21, 0x07, 21),
    Key("F", 27, 0x09, 27), Key("G", 33, 0x0a, 145), Key("H", 39, 0x0b, 39),
    Key("J", 45, 0x0d, 45), Key("K", 51, 0x0e, 51), Key("L", 57, 0x0f, 57),
    Key(";", 63, 0x33, 134), Key("'", 69, 0x34, 135), Key("Enter", 81, 0x28, 136),
    Key("Left Shift", 4, 0xe1, 4), Key("Z", 10, 0x1d, 10), Key("X", 16, 0x1b, 16),
    Key("C", 22, 0x06, 22), Key("V", 28, 0x19, 28), Key("B", 34, 0x05, 34),
    Key("N", 40, 0x11, 40), Key("M", 46, 0x10, 46), Key(",", 52, 0x36, 52),
    Key(".", 58, 0x37, 58), Key("/", 64, 0x38, 64), Key("Right Shift", 82, 0xe5, 82),
    Key("Up", 88, 0x52, 88), Key("Left Ctrl", 5, 0xe0, 5), Key("Left Super", 11, 0xe3, 144),
    Key("Left Alt", 17, 0xe2, 17), Key("Space", 35, 0x2c, 35), Key("Right Alt", 53, 0xe6, 146),
    # Right Ctrl's default entry is 20 01 00 00 (a special type, like Fn's 20 00 00 00). The official
    # software remapped it to E (00 00 00 08) and reset it back to 20 01 00 00 (user's log, 2026-11-06).
    Key("Right Ctrl", 65, 0xe4, 65, bytes.fromhex("20010000")),
    Key("Left", 83, 0x50, 139), Key("Down", 89, 0x51, 89), Key("Right", 95, 0x4f, 140),
)
REMAPPABLE = tuple(k for k in KEYS if k.remappable)

# Key rectangles (x1, y1, x2, y2) by key number, from the official software's Cfg.ini.
LAYOUT: dict[int, tuple[int, int, int, int]] = {
    1: (16, 54, 42, 81), 7: (53, 54, 79, 81), 13: (91, 54, 117, 81), 19: (128, 54, 154, 81),
    25: (166, 54, 192, 81), 31: (204, 54, 230, 81), 37: (241, 54, 267, 81), 43: (279, 54, 305, 81),
    49: (317, 54, 343, 81), 55: (354, 54, 380, 81), 61: (391, 54, 417, 81), 67: (429, 54, 455, 81),
    73: (466, 54, 492, 81), 79: (505, 54, 568, 81), 91: (580, 54, 606, 81), 93: (580, 129, 606, 156),
    2: (16, 92, 60, 119), 8: (72, 92, 98, 119), 14: (110, 92, 136, 119), 20: (147, 92, 173, 119),
    26: (185, 92, 211, 119), 32: (222, 92, 248, 119), 38: (260, 92, 286, 119), 44: (297, 92, 323, 119),
    50: (335, 92, 361, 119), 56: (372, 92, 398, 119), 62: (410, 92, 436, 119), 68: (448, 92, 474, 119),
    74: (485, 92, 511, 119), 80: (523, 92, 568, 119), 92: (580, 92, 606, 119), 94: (579, 167, 605, 194),
    3: (16, 129, 70, 156), 9: (81, 129, 107, 156), 15: (119, 129, 145, 156), 21: (156, 129, 182, 156),
    27: (194, 129, 220, 156), 33: (232, 129, 258, 156), 39: (269, 129, 295, 156), 45: (307, 129, 333, 156),
    51: (344, 129, 370, 156), 57: (382, 129, 408, 156), 63: (420, 129, 446, 156), 69: (457, 129, 483, 156),
    81: (495, 129, 567, 156), 4: (16, 167, 88, 194), 10: (100, 167, 126, 194), 16: (138, 167, 164, 194),
    22: (175, 167, 201, 194), 28: (213, 167, 239, 194), 34: (250, 167, 276, 194), 40: (288, 167, 314, 194),
    46: (326, 167, 352, 194), 52: (364, 167, 390, 194), 58: (400, 167, 426, 194), 64: (438, 167, 464, 194),
    82: (475, 167, 529, 194), 88: (541, 167, 567, 194), 5: (16, 204, 51, 231), 11: (63, 204, 98, 231),
    17: (110, 204, 145, 231), 35: (157, 204, 380, 231), 53: (392, 204, 418, 231), 59: (429, 204, 455, 231),
    65: (466, 204, 492, 231), 83: (504, 204, 530, 231), 89: (542, 204, 568, 231), 95: (579, 205, 605, 232),
}
# Keys drawn but never remapped: the Fn key and the special key right of it (type 20 entries).
SPECIAL = {59: "Fn"}
# Short keycap labels.
CAP_LABELS = {
    "Backspace": "⌫", "Delete": "Del", "Page Up": "PgUp", "Page Down": "PgDn", "Caps Lock": "Caps",
    "Left Shift": "Shift", "Right Shift": "Shift", "Left Ctrl": "Ctrl", "Right Ctrl": "Ctrl", "Left Super": "Win",
    "Left Alt": "Alt", "Right Alt": "Alt", "Space": "", "Up": "↑", "Down": "↓", "Left": "←",
    "Right": "→", "Enter": "Enter",
}
SHORT_TARGETS = {"Left Ctrl": "Ctrl", "Right Ctrl": "Ctrl", "Left Shift": "Shift", "Right Shift": "Shift",
                 "Left Alt": "Alt", "Right Alt": "Alt", "Left Super": "Win", "Right Super": "Win",
                 "Backspace": "⌫", "Delete": "Del", "Page Up": "PgUp", "Page Down": "PgDn",
                 "Caps Lock": "Caps", "Print Screen": "PrtSc", "Scroll Lock": "ScrLk", "Insert": "Ins",
                 "Up": "↑", "Down": "↓", "Left": "←", "Right": "→", "Space": "Space"}

# What a key can be remapped to: normal USB key codes only (type 00 entries).
TARGETS: dict[int, str] = {}
for _i in range(26):
    TARGETS[0x04 + _i] = chr(65 + _i)
for _i in range(9):
    TARGETS[0x1e + _i] = str(_i + 1)
TARGETS[0x27] = "0"
TARGETS.update({
    0x28: "Enter", 0x29: "Esc", 0x2a: "Backspace", 0x2b: "Tab", 0x2c: "Space", 0x2d: "-",
    0x2e: "=", 0x2f: "[", 0x30: "]", 0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",",
    0x37: ".", 0x38: "/", 0x39: "Caps Lock",
})
for _i in range(12):
    TARGETS[0x3a + _i] = f"F{_i + 1}"
TARGETS.update({
    0x46: "Print Screen", 0x47: "Scroll Lock", 0x48: "Pause", 0x49: "Insert", 0x4a: "Home",
    0x4b: "Page Up", 0x4c: "Delete", 0x4d: "End", 0x4e: "Page Down", 0x4f: "Right",
    0x50: "Left", 0x51: "Down", 0x52: "Up", 0x65: "Menu",
    0xe0: "Left Ctrl", 0xe1: "Left Shift", 0xe2: "Left Alt", 0xe3: "Left Super",
    0xe4: "Right Ctrl", 0xe5: "Right Shift", 0xe6: "Right Alt", 0xe7: "Right Super",
})
for _i in range(12):
    TARGETS[0x68 + _i] = f"F{_i + 13}"


class UnexpectedKeymap(ValueError):
    """The key map doesn't match the layout decoded for this keyboard; nothing is written."""


class VerifyFailed(RuntimeError):
    pass


def entries(data: bytes) -> list[bytes]:
    return [data[8 + 4 * i:12 + 4 * i] for i in range(256)]


def check(data: bytes) -> None:
    """Refuse a key map whose layout differs from the decoded one."""
    if len(data) < BLOCK_BUFFER_LEN or not data.startswith(READ_HEADER):
        raise UnexpectedKeymap("The key map has an unexpected header or length.")
    e = entries(data)
    for k in KEYS:
        at = e[k.number]
        entry = at[3] + POINTER_BASE if at[0] == POINTER else k.number
        if entry != k.entry:
            raise UnexpectedKeymap(f"{k.name} isn't where it's expected in the key map.")
        if k.special and e[entry] == k.special:
            continue
        if e[entry][0] == MACRO and e[entry][1] == 0 and e[entry][2] in (0x01, 0x04) \
                and 0x18 <= e[entry][3] < 0x20:
            continue
        if e[entry][0] != entry_type(e[entry][3]) or e[entry][1:3] != b"\0\0":
            raise UnexpectedKeymap(f"{k.name}'s entry has an unexpected type.")


def current(data: bytes) -> dict[str, int]:
    """Key name -> USB code it currently sends, for remappable keys."""
    check(data)
    e = entries(data)
    def code(k):
        x = e[k.entry]
        if k.special and x == k.special:
            return k.default
        if x[0] == MACRO:
            return MACRO_CODE + x[3] - 0x18
        return x[3]
    return {k.name: code(k) for k in REMAPPABLE}


def build_write(data: bytes, changes: dict[str, int]) -> bytes:
    check(data)
    by_name = {k.name: k for k in REMAPPABLE}
    out = bytearray(WRITE_HEADER + data[8:BLOCK_BUFFER_LEN])
    for name, code in changes.items():
        if name not in by_name:
            raise ValueError(f"{name} can't be remapped")
        if code not in TARGETS:
            raise ValueError("not a supported key code")
        key = by_name[name]
        off = 8 + 4 * key.entry
        if key.special and code == key.default:
            out[off:off + 4] = key.special
            continue
        out[off] = entry_type(code)
        out[off + 1:off + 3] = b"\0\0"
        out[off + 3] = code
    return bytes(out)


def read(devnode: str, **io) -> dict[str, int]:
    with Session(devnode, **io) as s:
        res = s.read_keymap()
    if not res.ok:
        raise UnexpectedKeymap(res.problem)
    return current(res.data)


def remap(devnode: str, changes: dict[str, int], **io) -> dict[str, int]:
    """Read the key map, change only the given keys, save it once, then read back and check."""
    capabilities.require_usable("remapping")
    with Session(devnode, **io) as s:
        res = s.read_keymap()
        if not res.ok:
            raise UnexpectedKeymap(res.problem)
        payload = build_write(res.data, changes)
        if payload[8:] == res.data[8:BLOCK_BUFFER_LEN]:
            return current(res.data)
        s.pause(SAVE_GAP)
        s.write_keymap(payload)
        s.pause(SAVE_GAP)
        after = s.read_keymap()
    if not after.ok:
        raise VerifyFailed(after.problem)
    now = current(after.data)
    if any(now[name] != code for name, code in changes.items()):
        raise VerifyFailed("The keyboard didn't keep the change.")
    return now


def reset_all(devnode: str, **io) -> dict[str, int]:
    return remap(devnode, {k.name: k.default for k in REMAPPABLE}, **io)


assert KEYMAP_REPLY_PREFIX == READ_HEADER[:3]
