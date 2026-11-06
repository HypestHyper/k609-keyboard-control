"""Entry point. `--inspect` prints what was found without starting the GUI."""

import os
import sys


def inspect(read: bool, lighting: bool = False) -> int:
    from .device import find_keyboards
    from .hidraw import AccessDenied, DeviceGone, hexdump, read_feature_reports, read_lighting_block

    keyboards = find_keyboards(os.environ.get("HORUS_CONTROL_SYSFS", "/sys"))
    if not keyboards:
        print("No wired 258a:0049 keyboard found.")
        return 1
    for kb in keyboards:
        print(f"{kb.label}  {kb.vendor_id:04x}:{kb.product_id:04x}  bcdDevice {kb.bcd_device}  {kb.usb_path}")
        for i in kb.interfaces:
            tag = "  <- configuration" if i.is_config_candidate else ""
            print(f"  interface {i.interface_number}  {i.devnode}  access={'yes' if i.access else 'no'}{tag}")
            if i.descriptor:
                for r in i.descriptor.reports:
                    print(f"    {r.kind:7} 0x{r.report_id:02x}  {r.payload_len} bytes")
            elif i.descriptor_error:
                print(f"    descriptor error: {i.descriptor_error}")
        iface = kb.config_interface
        if read and iface:
            try:
                for res in read_feature_reports(iface.devnode, iface.descriptor.feature_reports()):
                    print(f"  GET_FEATURE 0x{res.report_id:02x}: {len(res.data)}/{res.expected_len} bytes "
                          f"{res.problem}".rstrip())
                    print("    " + hexdump(res.data).replace("\n", "\n    "))
            except AccessDenied:
                print(f"  Access denied to {iface.devnode}. See README for the udev rule.")
            except DeviceGone:
                print("  Keyboard disconnected during the read.")
        if lighting and iface:
            try:
                res = read_lighting_block(iface.devnode)
                print(f"  Lighting block: {len(res.data)} bytes {res.problem}".rstrip())
                print("    " + hexdump(res.data[:262]).replace("\n", "\n    "))
            except AccessDenied:
                print(f"  Access denied to {iface.devnode}. See README for the udev rule.")
            except DeviceGone:
                print("  Keyboard disconnected during the read.")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--inspect" in args:
        return inspect("--read-features" in args, "--read-lighting" in args)
    if "--version" in args:
        from . import __version__
        print(__version__)
        return 0
    from .app import main as gui
    return gui()


if __name__ == "__main__":
    sys.exit(main())
