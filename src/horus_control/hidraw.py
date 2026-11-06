"""Linux hidraw access: report-descriptor parsing, GET_FEATURE and one read command.

SET_FEATURE is sent in exactly two shapes, both copied from a USB capture of the
official Redragon software: a command from ALLOWED_COMMANDS on report 0x05 (the
read request), and the lighting block saved back on report 0x06, checked by
is_lighting_write(). There is no output-report or write() call anywhere.
"""

from __future__ import annotations

import errno
import fcntl
import os
import time
from dataclasses import dataclass

# --- Report descriptor parsing -------------------------------------------------

VENDOR_USAGE_PAGE_MIN = 0xFF00

_MAIN_INPUT, _MAIN_OUTPUT, _MAIN_COLLECTION, _MAIN_FEATURE, _MAIN_END = 0x8, 0x9, 0xA, 0xB, 0xC


@dataclass(frozen=True)
class Report:
    kind: str          # "input", "output" or "feature"
    report_id: int
    bits: int

    @property
    def payload_len(self) -> int:
        """Payload bytes, excluding the report-ID byte."""
        return (self.bits + 7) // 8

    @property
    def buffer_len(self) -> int:
        """Bytes to pass to hidraw: one report-ID byte plus the payload."""
        return self.payload_len + 1


@dataclass(frozen=True)
class Collection:
    usage_page: int
    usage: int
    report_ids: tuple[int, ...]

    @property
    def is_vendor(self) -> bool:
        return self.usage_page >= VENDOR_USAGE_PAGE_MIN


@dataclass(frozen=True)
class Descriptor:
    reports: tuple[Report, ...]
    collections: tuple[Collection, ...]

    def feature_reports(self) -> tuple[Report, ...]:
        return tuple(r for r in self.reports if r.kind == "feature")

    @property
    def has_vendor_collection(self) -> bool:
        return any(c.is_vendor for c in self.collections)


class DescriptorError(ValueError):
    pass


def parse_descriptor(data: bytes) -> Descriptor:
    """Parse the parts of a HID report descriptor needed to size reports.

    Tracks report sizes per (kind, report ID) and the usage page/usage of each
    top-level application collection.
    """
    sizes: dict[tuple[str, int], int] = {}
    order: list[tuple[str, int]] = []
    collections: list[list] = []          # [usage_page, usage, set(report_ids)]
    glob = {"page": 0, "size": 0, "count": 0, "id": 0}
    stack: list[dict] = []
    usage = 0
    depth = 0
    i = 0
    n = len(data)
    while i < n:
        prefix = data[i]
        if prefix == 0xFE:                # long item: skip
            if i + 2 >= n:
                raise DescriptorError("truncated long item")
            i += 3 + data[i + 1]
            continue
        size = (0, 1, 2, 4)[prefix & 0x3]
        kind = (prefix >> 2) & 0x3
        tag = prefix >> 4
        if i + 1 + size > n:
            raise DescriptorError(f"truncated item at byte {i}")
        value = int.from_bytes(data[i + 1:i + 1 + size], "little")
        i += 1 + size

        if kind == 0:                     # main
            if tag in (_MAIN_INPUT, _MAIN_OUTPUT, _MAIN_FEATURE):
                name = {_MAIN_INPUT: "input", _MAIN_OUTPUT: "output", _MAIN_FEATURE: "feature"}[tag]
                key = (name, glob["id"])
                if key not in sizes:
                    sizes[key] = 0
                    order.append(key)
                sizes[key] += glob["size"] * glob["count"]
                if collections and depth > 0:
                    collections[-1][2].add(glob["id"])
            elif tag == _MAIN_COLLECTION:
                if depth == 0:
                    # Usage may carry its own page in a 4-byte item (page << 16 | id).
                    page = usage >> 16 if usage > 0xFFFF else glob["page"]
                    collections.append([page, usage & 0xFFFF, set()])
                depth += 1
            elif tag == _MAIN_END:
                depth = max(0, depth - 1)
            usage = 0
        elif kind == 1:                   # global
            if tag == 0x0:
                glob["page"] = value
            elif tag == 0x7:
                glob["size"] = value
            elif tag == 0x8:
                glob["id"] = value
            elif tag == 0x9:
                glob["count"] = value
            elif tag == 0xA:
                stack.append(dict(glob))
            elif tag == 0xB:
                if not stack:
                    raise DescriptorError("pop without push")
                glob = stack.pop()
        elif kind == 2:                   # local
            if tag == 0x0 and usage == 0:
                usage = value
            elif tag == 0x1 and usage == 0:  # usage minimum stands in for usage
                usage = value

    reports = tuple(Report(k, rid, sizes[(k, rid)]) for k, rid in order)
    cols = tuple(Collection(p, u, tuple(sorted(ids))) for p, u, ids in collections)
    return Descriptor(reports, cols)


# --- GET_FEATURE through hidraw -------------------------------------------------

def _ioc(direction: int, type_: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (type_ << 8) | nr


def hidiocgfeature(length: int) -> int:
    """HIDIOCGFEATURE(len) from linux/hidraw.h: _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, len)."""
    if not 0 < length < (1 << 14):
        raise ValueError("feature buffer length out of range")
    return _ioc(3, ord("H"), 0x07, length)


def hidiocsfeature(length: int) -> int:
    """HIDIOCSFEATURE(len): _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x06, len). Used only by _send_command."""
    if not 0 < length < (1 << 14):
        raise ValueError("feature buffer length out of range")
    return _ioc(3, ord("H"), 0x06, length)


# Seen in a USB capture of the official software (2026-11-06): it sends this on
# report 0x05, then reads report 0x06, which returns the lighting settings block.
READ_LIGHTING = bytes.fromhex("0583c6000000")
LIGHTING_REPLY_PREFIX = bytes.fromhex("0683c6")
ALLOWED_COMMANDS = frozenset({READ_LIGHTING})
BLOCK_BUFFER_LEN = 1032


class AccessDenied(Exception):
    pass


class DeviceGone(Exception):
    pass


@dataclass(frozen=True)
class FeatureResult:
    report_id: int
    expected_len: int     # buffer length including the report-ID byte
    data: bytes           # bytes the kernel returned (report-ID byte first)
    problem: str = ""     # empty when the reply looks well-formed

    @property
    def ok(self) -> bool:
        return not self.problem


def check_reply(report_id: int, expected_len: int, data: bytes) -> str:
    if not data:
        return "The keyboard returned no data."
    if data[0] != report_id:
        return f"The reply starts with report ID 0x{data[0]:02x}, not 0x{report_id:02x}."
    if len(data) < expected_len:
        return f"Short reply: {len(data)} of {expected_len} bytes."
    return ""


def _open(devnode, opener):
    try:
        return opener(devnode, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as e:
        if e.errno in (errno.EACCES, errno.EPERM):
            raise AccessDenied(devnode) from e
        if e.errno in (errno.ENOENT, errno.ENODEV, errno.ENXIO):
            raise DeviceGone(devnode) from e
        raise


def _send_command(fd, command: bytes, ioctl) -> None:
    if bytes(command) not in ALLOWED_COMMANDS:
        raise ValueError("command is not on the allow-list")
    buf = bytearray(command)
    ioctl(fd, hidiocsfeature(len(buf)), buf, True)


class WriteFailed(Exception):
    pass


LIGHTING_WRITE_HEADER = bytes.fromhex("0603c6")
BLOCK_LEN = 262            # meaningful bytes in the lighting block, header included


def is_lighting_write(buf: bytes) -> bool:
    """The only shape of SET_FEATURE 0x06 Horus Control may send: the lighting block saved back,
    as the official software does (06 03 c6, block marker 5a a5, zero padding to 1032 bytes)."""
    return (len(buf) == BLOCK_BUFFER_LEN and buf[:3] == LIGHTING_WRITE_HEADER
            and buf[14:16] == b"\x5a\xa5" and not any(buf[BLOCK_LEN:]))


def _lighting_problem(data: bytes) -> str:
    if not data.startswith(LIGHTING_REPLY_PREFIX):
        return "The reply doesn't start with 06 83 c6, so it isn't the lighting block."
    if len(data) < 22:
        return f"Short reply: {len(data)} bytes."
    return ""


class Session:
    """One open handle on the configuration interface for a read, or a read-write-verify."""

    def __init__(self, devnode: str, *, opener=os.open, ioctl=fcntl.ioctl, closer=os.close,
                 sleep=time.sleep):
        self.devnode, self._opener, self._ioctl, self._closer, self._sleep = devnode, opener, ioctl, closer, sleep
        self.fd = None

    def __enter__(self):
        self.fd = _open(self.devnode, self._opener)
        return self

    def __exit__(self, *exc):
        self._closer(self.fd)
        return False

    def _gone(self, e: OSError):
        if e.errno in (errno.ENODEV, errno.ENXIO, errno.ENOENT):
            raise DeviceGone(self.devnode) from e

    def read_lighting(self) -> FeatureResult:
        try:
            _send_command(self.fd, READ_LIGHTING, self._ioctl)
            self._sleep(0.02)
            buf = bytearray(BLOCK_BUFFER_LEN)
            buf[0] = 0x06
            n = self._ioctl(self.fd, hidiocgfeature(len(buf)), buf, True)
        except OSError as e:
            self._gone(e)
            return FeatureResult(0x06, BLOCK_BUFFER_LEN, b"", f"Read failed: {os.strerror(e.errno or 0)}.")
        n = n if isinstance(n, int) and n >= 0 else 0
        data = bytes(buf[:min(n, len(buf))])
        return FeatureResult(0x06, BLOCK_BUFFER_LEN, data, _lighting_problem(data))

    def write_lighting(self, payload: bytes) -> None:
        if not is_lighting_write(payload):
            raise ValueError("not a lighting block write")
        buf = bytearray(payload)
        try:
            self._ioctl(self.fd, hidiocsfeature(len(buf)), buf, True)
        except OSError as e:
            self._gone(e)
            raise WriteFailed(os.strerror(e.errno or 0)) from e
        self._sleep(0.1)


def read_lighting_block(devnode: str, **io) -> FeatureResult:
    """Ask for the lighting settings block, exactly as the official software does."""
    with Session(devnode, **io) as session:
        return session.read_lighting()


def read_feature_reports(devnode: str, reports, *, opener=os.open, ioctl=fcntl.ioctl,
                         closer=os.close) -> list[FeatureResult]:
    """Ask the device for each feature report with GET_FEATURE.

    The device node is opened only for the duration of the call and nothing is
    read from or written to its input/output stream, so no keystrokes are seen.
    """
    fd = _open(devnode, opener)
    results = []
    try:
        for rep in reports:
            buf = bytearray(rep.buffer_len)
            buf[0] = rep.report_id
            try:
                n = ioctl(fd, hidiocgfeature(len(buf)), buf, True)
            except OSError as e:
                if e.errno in (errno.ENODEV, errno.ENXIO, errno.ENOENT):
                    raise DeviceGone(devnode) from e
                results.append(FeatureResult(rep.report_id, rep.buffer_len, b"",
                                             f"Read failed: {os.strerror(e.errno or 0)}."))
                continue
            n = n if isinstance(n, int) and n >= 0 else 0
            data = bytes(buf[:min(n, len(buf))])
            results.append(FeatureResult(rep.report_id, rep.buffer_len, data,
                                         check_reply(rep.report_id, rep.buffer_len, data)))
    finally:
        closer(fd)
    return results


def diff_blocks(old: bytes, new: bytes, start: int = 3) -> list[tuple[int, int | None, int | None]]:
    """Byte offsets that differ between two settings blocks, skipping the 3-byte header."""
    out = []
    for i in range(start, max(len(old), len(new))):
        a = old[i] if i < len(old) else None
        b = new[i] if i < len(new) else None
        if a != b:
            out.append((i, a, b))
    return out


def describe_diff(changes) -> str:
    fmt = lambda v: "--" if v is None else f"{v:02x}"
    return ", ".join(f"byte {i}: {fmt(a)} → {fmt(b)}" for i, a, b in changes)


def hexdump(data: bytes, width: int = 16) -> str:
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off:off + width]
        lines.append(f"{off:04x}  {' '.join(f'{b:02x}' for b in chunk)}")
    return "\n".join(lines)
