"""App settings in ~/.config/k609-keyboard-control/settings.json, written atomically."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = 1
THEMES = ("system", "light", "dark")
SIZES = ("compact", "default", "large")
RECENT_MAX = 6


def remember(recent: list, hexv: str) -> list:
    """Most recent first, no repeats, at most RECENT_MAX."""
    return ([hexv] + [c for c in recent if c != hexv])[:RECENT_MAX]


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, "k609-keyboard-control")
    old = os.path.join(base, "horus-control")          # folder used before the app was renamed
    if not os.path.exists(path) and os.path.isdir(old):
        try:
            os.rename(old, path)
        except OSError:
            return old
    return path


@dataclass
class Settings:
    theme: str = "system"
    size: str = "default"
    reduce_motion: bool = False
    fixed_colour: str = ""            # last Fixed on colour sent, "rrggbb"; the keyboard can't report it
    desktop_entry: bool = True        # keep a launcher entry for the AppImage in ~/.local/share
    accent: str = "4d7cff"            # UI accent seed, "rrggbb"
    recent_colours: list = field(default_factory=list)   # last colours used in the colour pickers, "rrggbb"

    @classmethod
    def from_dict(cls, data) -> "Settings":
        s = cls()
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            return s
        if data.get("theme") in THEMES:
            s.theme = data["theme"]
        if data.get("size") in SIZES:
            s.size = data["size"]
        if isinstance(data.get("reduce_motion"), bool):
            s.reduce_motion = data["reduce_motion"]
        rc = data.get("recent_colours")
        if isinstance(rc, list):
            s.recent_colours = [c for c in rc if isinstance(c, str) and len(c) == 6
                                and all(x in "0123456789abcdef" for x in c)][:RECENT_MAX]
        ac = data.get("accent")
        if isinstance(ac, str) and len(ac) == 6 and all(c in "0123456789abcdef" for c in ac):
            s.accent = ac
        if isinstance(data.get("desktop_entry"), bool):
            s.desktop_entry = data["desktop_entry"]
        fc = data.get("fixed_colour")
        if isinstance(fc, str) and len(fc) == 6 and all(c in "0123456789abcdef" for c in fc):
            s.fixed_colour = fc
        return s

    def to_dict(self) -> dict:
        return {"version": SCHEMA_VERSION, **asdict(self)}


def load(path: str | None = None) -> Settings:
    path = path or os.path.join(config_dir(), "settings.json")
    try:
        with open(path, encoding="utf-8") as f:
            return Settings.from_dict(json.load(f))
    except (OSError, ValueError):
        return Settings()


def atomic_write_json(path: str, data) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(settings: Settings, path: str | None = None) -> None:
    atomic_write_json(path or os.path.join(config_dir(), "settings.json"), settings.to_dict())
