# Horus Control — notes for agents

- Spec: the Horus Control handover brief. UI follows the GTK App Family design language. Neither file is in this repo; ask the user if you need them.
- **Never add a HID write** (SET_FEATURE, output report, write()) until a K609GG protocol is
  proven with evidence and the user has reviewed it. Approved so far: the read command in
  `hidraw.ALLOWED_COMMANDS` (`05 83 c6 00 00 00` lighting, `05 84 d8 00 00 00` key map), plus these writes,
  each copied from captures of the official software: the lighting block
  save (`06 03 c6`, only decoded bytes changed) and the colour table (`06 08 c8`, must equal
  `colour_table.hex` except bytes 29–31), and the key map save (`06 04 d8 00 40`, built only by
  `keymap.py`; entry type 00/06 follows the code; Fn untouched; Right Ctrl resets to 20 01 00 00). Anything new needs the same capture evidence and user
  approval. Gate new features through
  `capabilities.require_usable()`; keep UI code away from raw bytes.
- Never open interface 0 or read input reports (no keystrokes).
- GTK 4 + PyGObject, no libadwaita. Styling lives only in `style.py`.
- Run `pytest` before committing.

Documented exceptions to the family design language:
- Fonts/icons: system font with "Google Sans Flex" preferred if installed; standard
  symbolic icons instead of bundled Material Symbols (not bundled, to keep v0.1 small).
- AppImage uses the host GTK 4/PyGObject (see README).
- Switch on-state thumb 20 px (provisional in the family spec).
- No automatic compact breakpoint; size is a setting.
