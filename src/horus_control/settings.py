"""App settings in ~/.config/horus-control/settings.json, written atomically."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass

SCHEMA_VERSION = 1
THEMES = ("system", "light", "dark")
SIZES = ("compact", "default", "large")


def config_dir() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "horus-control")


@dataclass
class Settings:
    theme: str = "system"
    size: str = "default"
    reduce_motion: bool = False
    fixed_colour: str = ""            # last Fixed on colour sent, "rrggbb"; the keyboard can't report it

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
