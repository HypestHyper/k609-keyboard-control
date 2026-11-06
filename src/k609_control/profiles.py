"""Profiles stored by Keyboard Control: lighting, key remaps and macros, applied together.

The keyboard has no profiles of its own: the official software's Profile 1/2/3 buttons rewrite the
colour table, key map and lighting block from its own copy (USB recording, 2026-11-06). Horus
Control does the same with the writes it already uses.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from . import keymap, lighting, macros, selfdefine
from .settings import atomic_write_json, config_dir

SCHEMA_VERSION = 1


@dataclass
class Profile:
    name: str
    effect: int
    levels: dict[int, int]                  # effect -> speed/brightness byte
    colour: str | None                      # Fixed on colour "rrggbb", if known
    keys: dict[str, int]                    # key name -> USB code (normal keys and modifiers)
    macros: list[macros.Macro] = field(default_factory=list)   # with their key assignments
    selfdef: dict[int, tuple[int, int, int]] = field(default_factory=dict)   # Self define key colours

    def to_dict(self) -> dict:
        return {"version": SCHEMA_VERSION, "name": self.name, "effect": self.effect,
                "levels": {f"{e:02x}": v for e, v in self.levels.items()}, "colour": self.colour,
                "keys": self.keys, "macros": [m.to_dict() for m in self.macros],
                "selfdefine": selfdefine.to_json(self.selfdef)}


def profiles_dir() -> str:
    return os.path.join(config_dir(), "profiles")


def file_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.") or "profile"
    return slug[:60] + ".json"


def validate(p: Profile) -> None:
    if not p.name.strip():
        raise ValueError("Give the profile a name.")
    if p.effect not in lighting.EFFECTS:
        raise ValueError("Unknown effect.")
    if set(p.levels) != set(lighting.LEVEL_EFFECTS) or any(
            not 0 <= v <= 0xFF or v >> 4 > lighting.MAX_LEVEL or v & 0xF > lighting.MAX_LEVEL
            for v in p.levels.values()):
        raise ValueError("Bad brightness or speed values.")
    if p.colour is not None and not re.fullmatch(r"[0-9a-f]{6}", p.colour):
        raise ValueError("Bad colour.")
    names = {k.name for k in keymap.REMAPPABLE}
    if set(p.keys) - names:
        raise ValueError("Unknown key in profile.")
    if any(code not in keymap.TARGETS for code in p.keys.values()):
        raise ValueError("Unsupported key code in profile.")
    for m in p.macros:
        macros.validate(m)
    assigned = [m.key for m in p.macros if m.key]
    if len(assigned) != len(set(assigned)) or len(assigned) > macros.SLOTS:
        raise ValueError("Bad macro assignments in profile.")


def from_dict(data) -> Profile:
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
        raise ValueError("Unsupported profile file.")
    names = {k.name for k in keymap.REMAPPABLE}
    ms = []
    for item in data.get("macros", []):
        ms.append(macros.Macro(str(item["name"]),
                               [macros.Step(int(s["key"]), bool(s["down"]), int(s["pause"])) for s in item["steps"]],
                               bool(item.get("held", False)), int(item.get("count", 1)),
                               item.get("key") if item.get("key") in names else None))
    p = Profile(str(data["name"]), int(data["effect"]),
                {int(k, 16): int(v) for k, v in data["levels"].items()},
                data.get("colour"), {str(k): int(v) for k, v in data["keys"].items()}, ms,
                selfdefine.from_json(data.get("selfdefine", {})))
    validate(p)
    return p


def save(p: Profile, folder: str | None = None) -> str:
    validate(p)
    path = os.path.join(folder or profiles_dir(), file_name(p.name))
    atomic_write_json(path, p.to_dict())
    return path


def load_all(folder: str | None = None) -> list[Profile]:
    folder = folder or profiles_dir()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, n), encoding="utf-8") as f:
                out.append(from_dict(json.load(f)))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return out


def find(name: str, folder: str | None = None) -> Profile | None:
    for p in load_all(folder):
        if p.name.lower() == name.lower() or file_name(p.name) == file_name(name):
            return p
    return None


def delete(name: str, folder: str | None = None) -> None:
    os.remove(os.path.join(folder or profiles_dir(), file_name(name)))


def capture(devnode: str, name: str, colour: str | None, current_macros: list[macros.Macro],
            selfdef: dict | None = None, **io) -> Profile:
    """Read the keyboard's lighting and keys; macros and colour come from Keyboard Control's own copy."""
    st = lighting.read_state(devnode, **io)
    keys = keymap.read(devnode, **io)
    assigned = {m.key for m in current_macros if m.key}
    normal = {k: c for k, c in keys.items() if c < keymap.MACRO_CODE and k not in assigned}
    p = Profile(name, st.effect, dict(st.levels), colour, normal,
                [macros.Macro(m.name, [macros.Step(s.key, s.down, s.pause) for s in m.steps], m.held, m.count, m.key)
                 for m in current_macros], dict(selfdef or {}))
    validate(p)
    return p


def apply(devnode: str, p: Profile, **io) -> None:
    """Write the profile's lighting, keys and macros, each with its verified write."""
    validate(p)
    rgb = tuple(bytes.fromhex(p.colour)) if p.colour else None
    lighting.apply(devnode, effect=p.effect, levels=p.levels, colour=rgb, **io)
    if p.effect == lighting.SELF_DEFINE and p.selfdef:
        selfdefine.apply(devnode, p.selfdef, **io)
    macro_keys = {m.key for m in p.macros if m.key}
    changes = {k.name: p.keys.get(k.name, k.default) for k in keymap.REMAPPABLE if k.name not in macro_keys}
    keymap.remap(devnode, changes, **io)
    macros.apply(devnode, p.macros, **io)


def export_to(p: Profile, path: str) -> None:
    """Write a profile to any file the user chose (same format as the saved profiles)."""
    validate(p)
    atomic_write_json(path, p.to_dict())


def import_from(path: str, folder: str | None = None) -> Profile:
    """Read and validate a profile file, then save it; a clashing name gets a number added."""
    with open(path, encoding="utf-8") as f:
        try:
            p = from_dict(json.load(f))
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError("That file isn't a profile from this app.") from e
    taken = {x.name.lower() for x in load_all(folder)}
    base, n = p.name, 2
    while p.name.lower() in taken:
        p.name = f"{base} {n}"
        n += 1
    save(p, folder)
    return p
