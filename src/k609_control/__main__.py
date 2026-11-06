"""Entry point. `--inspect` prints what was found without starting the GUI."""

import os
import sys


def inspect(read: bool, lighting: bool = False) -> int:
    from .device import find_keyboards
    from .hidraw import AccessDenied, DeviceGone, hexdump, read_feature_reports, read_lighting_block

    keyboards = find_keyboards(os.environ.get("K609_SYSFS", "/sys"))
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


def notify(text: str, error: bool = False) -> None:
    print(text, file=sys.stderr if error else sys.stdout)
    if not sys.stdout.isatty():             # started from a key binding: show a desktop notification
        import shutil
        import subprocess
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-a", "Keyboard Control", "-t", "2500", text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply_profile(name: str) -> int:
    from . import macros, profiles, settings
    from .device import find_keyboards
    from .hidraw import AccessDenied, DeviceGone

    p = profiles.find(name)
    if p is None:
        known = ", ".join(x.name for x in profiles.load_all()) or "none saved yet"
        notify(f"No profile called “{name}”. Profiles: {known}.", error=True)
        return 2
    kbs = [k for k in find_keyboards(os.environ.get("K609_SYSFS", "/sys")) if k.config_interface]
    if len(kbs) != 1:
        notify("Keyboard not found." if not kbs else "More than one K609GG is connected.", error=True)
        return 1
    try:
        profiles.apply(kbs[0].config_interface.devnode, p)
    except AccessDenied:
        notify("Can't open the keyboard. Open Keyboard Control to see how to allow access.", error=True)
        return 1
    except (DeviceGone, OSError, ValueError, RuntimeError) as e:
        notify(f"Couldn't apply “{p.name}”: {e}", error=True)
        return 1
    # keep the app's own copies in step with the keyboard
    macros.save(p.macros)
    s = settings.load()
    if p.colour:
        s.fixed_colour = p.colour
        settings.save(s)
    notify(f"Applied profile “{p.name}”.")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if "--apply-profile" in args:
        i = args.index("--apply-profile")
        if i + 1 >= len(args):
            print("Usage: k609-keyboard-control --apply-profile NAME", file=sys.stderr)
            return 2
        return apply_profile(args[i + 1])
    if "--smoke-test" in args:
        # Opens the window, checks it draws, then quits: used by the release workflow on other distros.
        os.environ["K609_SMOKE_TEST"] = "1"
        from .app import main as gui
        return gui()
    if "--help" in args or "-h" in args:
        print("Usage: k609-keyboard-control [--apply-profile NAME | --list-profiles | --inspect "
              "[--read-features] [--read-lighting] | --version | --smoke-test]")
        return 0
    if "--list-profiles" in args:
        from . import profiles
        for p in profiles.load_all():
            print(p.name)
        return 0
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
