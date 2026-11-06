# Horus Control — notes for agents

- Spec: the Horus Control handover brief. UI follows the GTK App Family design language. Neither file is in this repo; ask the user if you need them.
- **Never add a HID write** (SET_FEATURE, output report, write()) until a K609GG protocol is
  proven with evidence and the user has reviewed it. Gate new features through
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
