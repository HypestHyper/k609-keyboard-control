"""Find the wired K609GG through sysfs, without opening any device node."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .hidraw import Descriptor, DescriptorError, parse_descriptor

VENDOR_ID = 0x258A
PRODUCT_ID = 0x0049
CONFIG_INTERFACE = 1
BUS_USB = 0x0003


@dataclass(frozen=True)
class HidInterface:
    name: str                    # e.g. "hidraw12" (changes between boots; never stored)
    devnode: str                 # e.g. "/dev/hidraw12"
    interface_number: int | None
    descriptor_bytes: bytes
    descriptor: Descriptor | None
    descriptor_error: str = ""
    access: bool = False         # current user may open the node read/write

    @property
    def is_config_candidate(self) -> bool:
        return (self.interface_number == CONFIG_INTERFACE and self.descriptor is not None
                and self.descriptor.has_vendor_collection
                and bool(self.descriptor.feature_reports()))


@dataclass(frozen=True)
class Keyboard:
    usb_path: str                # sysfs path of the USB device: identifies one keyboard
    manufacturer: str
    product: str
    vendor_id: int
    product_id: int
    bcd_device: str
    usb_version: str
    serial: str
    interfaces: tuple[HidInterface, ...] = field(default_factory=tuple)

    @property
    def config_interface(self) -> HidInterface | None:
        for iface in self.interfaces:
            if iface.is_config_candidate:
                return iface
        return None

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.product}".strip() or "Keyboard"


def _read(path: str, binary: bool = False):
    try:
        with open(path, "rb" if binary else "r") as f:
            data = f.read()
    except OSError:
        return b"" if binary else ""
    return data if binary else data.strip()


def _uevent(path: str) -> dict[str, str]:
    out = {}
    for line in _read(os.path.join(path, "uevent")).splitlines():
        key, _, value = line.partition("=")
        out[key] = value
    return out


def parse_hid_id(value: str) -> tuple[int, int, int] | None:
    """'0003:0000258A:00000049' -> (bus, vendor, product)."""
    parts = value.split(":")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(p, 16) for p in parts)  # type: ignore[return-value]
    except ValueError:
        return None


def _default_access(devnode: str) -> bool:
    return os.access(devnode, os.R_OK | os.W_OK)


def find_keyboards(sysfs: str = "/sys", dev: str = "/dev", access=_default_access) -> list[Keyboard]:
    """List every wired 258a:0049 keyboard, grouping its HID interfaces."""
    class_dir = os.path.join(sysfs, "class", "hidraw")
    try:
        names = sorted(os.listdir(class_dir), key=lambda s: (len(s), s))
    except OSError:
        return []

    groups: dict[str, list[HidInterface]] = {}
    for name in names:
        hid_dir = os.path.realpath(os.path.join(class_dir, name, "device"))
        ids = parse_hid_id(_uevent(hid_dir).get("HID_ID", ""))
        if ids != (BUS_USB, VENDOR_ID, PRODUCT_ID):
            continue
        iface_dir = os.path.dirname(hid_dir)
        usb_dir = os.path.dirname(iface_dir)
        num = _read(os.path.join(iface_dir, "bInterfaceNumber"))
        try:
            iface_num = int(num, 16)
        except ValueError:
            iface_num = None
        raw = _read(os.path.join(hid_dir, "report_descriptor"), binary=True)
        try:
            desc, err = parse_descriptor(raw), ""
        except DescriptorError as e:
            desc, err = None, str(e)
        devnode = os.path.join(dev, name)
        groups.setdefault(usb_dir, []).append(
            HidInterface(name, devnode, iface_num, raw, desc, err, bool(access(devnode))))

    keyboards = []
    for usb_dir, ifaces in groups.items():
        keyboards.append(Keyboard(
            usb_path=usb_dir,
            manufacturer=_read(os.path.join(usb_dir, "manufacturer")),
            product=_read(os.path.join(usb_dir, "product")),
            vendor_id=VENDOR_ID,
            product_id=PRODUCT_ID,
            bcd_device=_read(os.path.join(usb_dir, "bcdDevice")),
            usb_version=_read(os.path.join(usb_dir, "version")),
            serial=_read(os.path.join(usb_dir, "serial")),
            interfaces=tuple(sorted(ifaces, key=lambda i: (i.interface_number is None,
                                                           i.interface_number or 0))),
        ))
    return sorted(keyboards, key=lambda k: k.usb_path)


UDEV_RULE = """\
# Keyboard Control: let the logged-in user open the K609GG configuration interface.
# Wired USB 258a:0049, HID interface 1 only. Typing interface 0 is left alone.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="258a", ATTRS{idProduct}=="0049", ENV{HORUS_K609GG}="1"
SUBSYSTEM=="hidraw", ENV{HORUS_K609GG}=="1", ATTRS{bInterfaceNumber}=="01", TAG+="uaccess"
"""
