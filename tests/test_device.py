import os

from fixtures import IFACE0, IFACE1

from k609_control.device import CONFIG_INTERFACE, find_keyboards


def make_tree(root, devices):
    """devices: list of (usb_name, vid, pid, [(iface_num, hidraw_name, descriptor)])"""
    os.makedirs(root / "class" / "hidraw", exist_ok=True)
    for usb_name, vid, pid, ifaces in devices:
        usb = root / "devices" / "pci0000:00" / "usb3" / usb_name
        usb.mkdir(parents=True)
        (usb / "idVendor").write_text(f"{vid:04x}\n")
        (usb / "idProduct").write_text(f"{pid:04x}\n")
        (usb / "manufacturer").write_text("BY Tech\n")
        (usb / "product").write_text("Gaming Keyboard\n")
        (usb / "bcdDevice").write_text("0102\n")
        (usb / "version").write_text(" 1.10\n")
        for num, name, desc in ifaces:
            iface = usb / f"{usb_name}:1.{num}"
            hid = iface / f"0003:{vid:04X}:{pid:04X}.{num + 14:04X}"
            hid.mkdir(parents=True)
            (iface / "bInterfaceNumber").write_text(f"{num:02x}\n")
            (hid / "uevent").write_text(f"DRIVER=hid-generic\nHID_ID=0003:0000{vid:04X}:0000{pid:04X}\n")
            (hid / "report_descriptor").write_bytes(desc)
            node = root / "class" / "hidraw" / name
            node.mkdir()
            (node / "device").symlink_to(hid)


def test_finds_keyboard_and_config_interface(tmp_path):
    make_tree(tmp_path, [("3-2", 0x258A, 0x0049, [(0, "hidraw3", IFACE0), (1, "hidraw7", IFACE1)])])
    kbs = find_keyboards(str(tmp_path), "/dev", access=lambda p: False)
    assert len(kbs) == 1
    kb = kbs[0]
    assert kb.manufacturer == "BY Tech" and kb.bcd_device == "0102"
    cfg = kb.config_interface
    assert cfg.interface_number == CONFIG_INTERFACE
    assert cfg.devnode == "/dev/hidraw7"    # from enumeration, never hard-coded
    assert not cfg.access


def test_node_numbers_do_not_matter(tmp_path):
    # Interface 1 enumerated first and on a lower node number than interface 0.
    make_tree(tmp_path, [("1-4", 0x258A, 0x0049, [(1, "hidraw0", IFACE1), (0, "hidraw12", IFACE0)])])
    kb = find_keyboards(str(tmp_path), "/dev", access=lambda p: True)[0]
    assert kb.config_interface.name == "hidraw0"
    assert [i.interface_number for i in kb.interfaces] == [0, 1]


def test_ignores_other_devices_and_receiver(tmp_path):
    make_tree(tmp_path, [
        ("3-1", 0x25A7, 0xFA70, [(0, "hidraw1", IFACE0), (1, "hidraw2", IFACE1)]),
        ("3-3", 0x258A, 0x0050, [(1, "hidraw4", IFACE1)]),
    ])
    assert find_keyboards(str(tmp_path), "/dev", access=lambda p: True) == []


def test_interface1_without_vendor_reports_is_not_used(tmp_path):
    make_tree(tmp_path, [("3-2", 0x258A, 0x0049, [(0, "hidraw3", IFACE0), (1, "hidraw4", IFACE0)])])
    assert find_keyboards(str(tmp_path), "/dev", access=lambda p: True)[0].config_interface is None


def test_two_keyboards_listed_separately(tmp_path):
    make_tree(tmp_path, [
        ("3-2", 0x258A, 0x0049, [(0, "hidraw3", IFACE0), (1, "hidraw4", IFACE1)]),
        ("3-5", 0x258A, 0x0049, [(0, "hidraw5", IFACE0), (1, "hidraw6", IFACE1)]),
    ])
    kbs = find_keyboards(str(tmp_path), "/dev", access=lambda p: True)
    assert [k.config_interface.name for k in kbs] == ["hidraw4", "hidraw6"]


def test_no_sysfs(tmp_path):
    assert find_keyboards(str(tmp_path / "missing")) == []


def test_corrupt_descriptor_is_reported_not_raised(tmp_path):
    make_tree(tmp_path, [("3-2", 0x258A, 0x0049, [(1, "hidraw4", b"\x06\x00\xff\x26\xff")])])
    iface = find_keyboards(str(tmp_path), "/dev", access=lambda p: True)[0].interfaces[0]
    assert iface.descriptor is None and iface.descriptor_error


def test_packaged_udev_rule_matches_app():
    from pathlib import Path

    from k609_control.device import UDEV_RULE
    rule = (Path(__file__).parent.parent / "packaging" / "70-horus-control.rules").read_text()
    assert rule == UDEV_RULE
    assert "0666" not in rule and 'ATTRS{bInterfaceNumber}=="01"' in rule
