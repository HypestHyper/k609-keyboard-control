# Horus Control

A small GTK 4 app for the **Redragon Horus SE K609GG** keyboard over **wired USB** (`258a:0049`).

**Status: v0.7.1.** It finds the keyboard, picks its configuration interface
(HID interface 1) and, on request, reads the lighting settings block. To do that it sends one
fixed read request (`05 83 c6 00 00 00` on report `0x05`), which is the one the official Redragon
software sends. That is the only command the app can send, and it **changes no settings**. It never
opens the typing interface (interface 0) and never reads keystrokes. Lighting, remapping,
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

Without a window, to print what's found and the lighting block:

```bash
PYTHONPATH=src python -m horus_control --inspect --read-lighting
```

## AppImage

```bash
./tools/build-appimage.sh
./dist/Horus_Control-0.7.1-x86_64.AppImage
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

## Lighting tab

Changes the effect, and each effect's brightness and speed (0–4). Each change reads the
lighting block, changes only those bytes, saves it with the same command Redragon's software uses
(`06 03 c6 …`), then reads it back to check. Before the first change, the effect, brightness and
speed values are saved to `~/.config/horus-control/lighting-backup.json`, and **Restore** puts them
back.

**Fixed on colour.** The colour is bytes 29–31 (red, green, blue) of a separate colour table
(`06 08 c8 …`) that the keyboard can't report back. Redragon's software always sends the whole table
before saving. Horus Control does the same: it sends the table as recorded from Redragon's software
(`src/horus_control/colour_table.hex`, identical across 16 recorded saves apart from those 3 bytes)
with your colour, then saves the lighting block unchanged. Other effects' colours in that table are
not decoded, so they're always sent as recorded. Restore can't undo a colour.

Every save copies the official software's sequence and timing: read command, 20 ms, read,
20 ms, colour table, 50 ms, lighting block, 40 ms, and the whole save twice. The colour table is
included with the last colour Horus Control set; if it has never set one, the table is left out.
Like the official software (through Wine), Horus Control keeps the configuration interface open
while it runs instead of opening it for each action, which made the LEDs flash. It never reads
the input reports that queue on that handle.

Decoded layout of the lighting block (byte offsets include the 3-byte header):

| Byte | Meaning |
|---|---|
| 20 | `01` for Self define, otherwise `00` |
| 21 | Effect: `00` Off, `01`–`12` effects, `15` Self define |
| 39 + 2 × (effect − 1) | That effect's speed (high digit) and brightness (low digit), 0–4 each |

## Keys tab (key remapping)

`05 84 d8 00 00 00` then GET `0x06` returns the key map (starts `06 84 d8 00 84`): an 8-byte header,
then 256 entries of 4 bytes (type, two zero bytes, USB key code). Types: `00` normal key, `02`
pointer, `04` media key, `06` modifier, `0e` Fn function, `20` Fn key.

Each key's entry is its key number from Redragon's `Cfg.ini`; if that entry is a pointer (`02`),
the key's real entry is its code + 132. This places all 66 non-Fn keys on an entry holding their
default code, and matches the two remaps recorded from Redragon's software (Caps Lock = 143,
Esc = 147). Saves use `06 04 d8 00 40 00 00 00` + the map, once, then Horus Control reads it back
to check. Horus Control's saves for the recorded remap and reset are byte-for-byte identical to
Redragon's.

Supported: normal keys to normal key codes (letters, numbers, punctuation, F1–F24, navigation,
editing keys). Not yet: modifiers, media keys, Fn. **Reset all keys** restores every key's
default code and works with the mouse alone.

## Finding what each setting does

Open Redragon's software (in Bottles) and Horus Control side by side. Pick and apply one thing in
Redragon's software, type its name in Horus Control and press Enter. Horus Control reads the
lighting block and adds the changed bytes to **Your list**. When done, press **Copy list**.
Horus Control only reads when you press Enter, never in the background, so it can't collide with
Redragon's own read-then-write of the key map.

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
- Protocol, from a USB capture of the official software: send a 6-byte command on report
  `0x05`, then read or write report `0x06`. `05 83 c6 …` then GET `0x06` returns the lighting
  block (starts `06 83 c6`). `06 03 c6 …` writes it back. `05 84 d8 …` / `06 04 d8 …` read and
  write a key-map block. `06 08 c8 …` and `06 09 cc/d0 …` are unknown tables.
- In the lighting block, byte 21 changes with the effect (seen values `01`, `0e`, `07`, `15`)
  and byte 20 changed once (`00` to `01`). Nothing else is decoded.
- The 2.4 GHz receiver (`25a7:fa70`) and Bluetooth are out of scope.
