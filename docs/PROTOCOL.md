# Protocol notes

How the app talks to the keyboard, decoded from USB recordings of the official software. Everything the app writes is copied from those recordings.

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

## Lighting tab

Changes the effect, and each effect's brightness and speed (0–4). Each change reads the
lighting block, changes only those bytes, saves it with the same command Redragon's software uses
(`06 03 c6 …`), then reads it back to check. Before the first change, the effect, brightness and
speed values are saved to `~/.config/k609-keyboard-control/lighting-backup.json`, and **Restore** puts them
back.

**Fixed on colour.** The colour is bytes 29–31 (red, green, blue) of a separate colour table
(`06 08 c8 …`) that the keyboard can't report back. Redragon's software always sends the whole table
before saving. Keyboard Control does the same: it sends the table as recorded from Redragon's software
(`src/k609_control/colour_table.hex`, identical across 16 recorded saves apart from those 3 bytes)
with your colour, then saves the lighting block unchanged. Other effects' colours in that table are
not decoded, so they're always sent as recorded. Restore can't undo a colour.

Every save copies the official software's sequence and timing: read command, 20 ms, read,
20 ms, colour table, 50 ms, lighting block, 40 ms, and the whole save twice. The colour table is
included with the last colour Keyboard Control set; if it has never set one, the table is left out.
Like the official software (through Wine), Keyboard Control keeps the configuration interface open
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
Esc = 147). Saves use `06 04 d8 00 40 00 00 00` + the map, once, then Keyboard Control reads it back
to check. Keyboard Control's saves for the recorded remap and reset are byte-for-byte identical to
Redragon's.

The entry type follows the code: `06` for modifiers (`e0`–`e7`), `00` otherwise. This was confirmed
by remapping Ctrl, Shift, Win and Alt to letters and back in Redragon's software.

Supported: every key except Fn (Right Ctrl's default entry is the special `20 01 00 00`, restored on reset), to letters, numbers, punctuation,
F1–F24, navigation and editing keys, or modifiers. Not yet: media keys. Remapping a normal key to a
modifier (for example Caps Lock to Ctrl) isn't offered by Redragon's software; it uses the same entry
format as the keyboard's own modifier keys. **Reset all keys** restores every key's
default code and works with the mouse alone.

## Macros tab

Macros are key presses and releases with pauses, played by a normal key, stored in the keyboard.
Decoded from four macros saved by Redragon's software (all reproduced byte for byte):

- Macro block, saved with `06 05 e8 00 40 00 00 00`: 128-byte slots. A slot is `00`, the repeat
  count, then 2-byte events `[timing, key]`. `0x80` in timing = key release; its low 7 bits = pause
  after the event in ms (1–127). Longer pauses: timing `03`, then `00 03` and a 2-byte count of 100 ms.
- The key's key map entry: `10 00 <mode> <0x18 + slot>`, mode `01` = repeat N times, `04` = while held.
- Save order: read key map, write macro block, write key map.

The keyboard can't report macros back, so Keyboard Control keeps them in
`~/.config/k609-keyboard-control/macros.json` and writes all assigned macros together (up to 8). This
replaces macros set in Redragon's software. G1–G4 (recorded with MR on the keyboard) and mouse
buttons aren't supported.

## Profiles

The keyboard has no profiles of its own: Redragon's Profile 1/2/3 buttons rewrite the colour table,
key map and lighting block from the software's copy. Keyboard Control profiles do the same. A profile
(lighting, key remaps, macros) is saved in `~/.config/k609-keyboard-control/profiles/<name>.json` and written
to the keyboard when applied.

Apply from the Profiles tab, or from the command line (it applies, prints the result, shows a desktop
notification when started from a key binding, and exits):

```bash
./dist/K609_Keyboard_Control-0.11.1-x86_64.AppImage --apply-profile Gaming
```

To switch from the keyboard, remap a spare key to F13–F24 and bind it in Hyprland, for example:

```
bind = , F13, exec, "/path/to/Horus_Control.AppImage" --apply-profile "Gaming"
```

`--list-profiles` prints the saved profile names.

Profiles can be exported to a file and imported again (Profiles tab). An imported profile whose
name is taken gets a number added.

## Self define (per-key colours)

Saved with two tables. `06 09 cc 00 40 …` starts with three 126-byte planes (red, green, blue)
after its 8-byte header; a key's byte is its colour index from Redragon's `Cfg.ini` (the second
number of its key entry), so Esc (21) red is byte 29 and A (64) green is byte 8 + 126 + 64 = 198.
The rest of that table and all of `06 09 d0 …` never change and are sent as recorded. Order: read
the lighting block, 20 ms, colour table, 50 ms, second table, 50 ms, lighting block with effect
`15` (Self define). The colours can't be read back.
