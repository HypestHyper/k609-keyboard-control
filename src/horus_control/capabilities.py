"""What Horus Control is allowed to change. Nothing is verified yet."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    HARDWARE = "hardware_supported"   # proven; stored by the keyboard firmware
    HOST = "host_supported"           # done by this app on Linux, not the keyboard
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Capability:
    key: str
    title: str
    status: Status
    evidence: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability("lighting", "Effect, brightness and speed", Status.HARDWARE,
               "Decoded from the lighting block; saved with the same command as Redragon's software."),
    Capability("lighting_colour", "Fixed on colour", Status.HARDWARE,
               "Bytes 29–31 of the colour table, from three recordings of Redragon's software. "
               "Other effects' colours aren't decoded."),
    Capability("remapping", "Key remapping", Status.HARDWARE,
               "Every key except Fn, to normal keys or modifiers. Key positions decoded from the key "
               "map and recorded remaps. Media keys aren't supported yet."),
    Capability("macros", "Macros", Status.HARDWARE,
               "Key presses and pauses on normal keys, decoded from four macros saved by Redragon's "
               "software. G1–G4 and mouse buttons aren't supported."),
    Capability("media_keys", "Media keys", Status.UNKNOWN, "No protocol evidence yet."),
    Capability("profiles", "Profiles", Status.HOST,
               "Saved by Horus Control and written to the keyboard when applied. The keyboard has no "
               "profiles of its own; Redragon's software works the same way."),
    Capability("polling_rate", "Polling rate", Status.UNKNOWN, "No protocol evidence yet."),
)


class NotVerified(RuntimeError):
    pass


def get(key: str) -> Capability:
    for cap in CAPABILITIES:
        if cap.key == key:
            return cap
    raise KeyError(key)


def require_usable(key: str) -> Capability:
    """Gate every future device operation on this. Unknown features cannot run."""
    cap = get(key)
    if cap.status not in (Status.HARDWARE, Status.HOST):
        raise NotVerified(f"{cap.title} is not verified for this keyboard.")
    return cap
