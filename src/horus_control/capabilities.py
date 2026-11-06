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
    Capability("lighting", "Lighting", Status.UNKNOWN,
               "Feature reports 0x05 and 0x06 exist; their meaning is not decoded."),
    Capability("remapping", "Key remapping", Status.UNKNOWN, "No protocol evidence yet."),
    Capability("macros", "Macros", Status.UNKNOWN, "No protocol evidence yet."),
    Capability("media_keys", "Media keys", Status.UNKNOWN, "No protocol evidence yet."),
    Capability("onboard_profiles", "On-board profiles", Status.UNKNOWN, "No protocol evidence yet."),
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
