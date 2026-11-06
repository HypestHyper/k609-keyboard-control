# Horus Control

A small GTK 4 app for the **Redragon Horus SE K609GG** keyboard over **wired USB** (`258a:0049`).

**Status: read-only inspector (v0.1).** It finds the keyboard, picks its configuration
interface (HID interface 1), shows the reports that interface declares, and on request reads
feature reports `0x05` and `0x06` with `GET_FEATURE`. It **never writes** to the keyboard,
never opens the typing interface (interface 0) and never reads keystrokes. Lighting, remapping,
macros and the rest stay hidden until their protocol is proven on this keyboard.

## Run

Needs GTK 4 and PyGObject from the system. On CachyOS/Arch:

```bash
sudo pacman -S --needed python-gobject gtk4
```

From the source folder:

```bash
PYTHONPATH=src python -m horus_control
```

Without a window, to print what's found (`--read-features` adds the read-only GET_FEATURE):

```bash
PYTHONPATH=src python -m horus_control --inspect --read-features
```

## AppImage

```bash
./tools/build-appimage.sh
./dist/Horus_Control-0.1.0-x86_64.AppImage
```

The script downloads `appimagetool` 1.9.0 into `build/` the first time.

The AppImage bundles the app, but **uses the host's Python, GTK 4 and PyGObject**. The app is
pure Python and has no native dependencies of its own (it talks to hidraw through ioctls,
so no `hidapi`). Bundling all of GTK 4 is
much larger and more fragile, since graphics drivers must still come from the host. On CachyOS,
`python-gobject` and `gtk4` are normal packages. If they're missing, the AppImage says so.

## Permission (optional, done by you)

The configuration interface `/dev/hidrawN` is usually root-only. The app shows this and
doesn't ask for root. To allow your logged-in user to open **only interface 1 of this
keyboard**, install the rule in `packaging/70-horus-control.rules`:

```bash
sudo install -m 644 packaging/70-horus-control.rules /etc/udev/rules.d/70-horus-control.rules
```

```bash
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
```

Then unplug and reconnect the keyboard. Check that it applied to the right node:

```bash
getfacl /dev/hidraw* 2>/dev/null | grep -B3 "user:$USER"
```

Remove it:

```bash
sudo rm /etc/udev/rules.d/70-horus-control.rules && sudo udevadm control --reload
```

The rule uses `TAG+="uaccess"` (a session ACL for the active user), never mode `0666`.

## Settings

`~/.config/horus-control/settings.json` (theme, size, reduce motion). The folder is created
only when you change a setting. No logs are written.

## Tests

```bash
pytest
```

The tests use a fake sysfs tree and a fake device, so they don't need the keyboard.
For development, `HORUS_CONTROL_SYSFS=/path/to/fake/sys` points the scan at a fake tree.

## Known facts

- Interface 1 declares feature report `0x05` (5 bytes) and `0x06` (1031 bytes), plus one
  report-ID byte each when read. There is no report `0x08`.
- Every byte read is shown as opaque hex; nothing is interpreted yet.
- The 2.4 GHz receiver (`25a7:fa70`) and Bluetooth are out of scope.
