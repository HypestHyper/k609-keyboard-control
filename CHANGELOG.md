# Changelog

## 0.14.1 (2026-11-07)

- **Allow access** button: asks for your password and adds the keyboard's access rule, so you don't need a terminal.
  The commands are still in Settings.
- Warnings are amber now, and "Keyboard not found" has a short list of what to check.

## 0.14.0 (2026-11-07)

- **Undo:** a button in the header and Ctrl+Z undo your last changes (lighting, colours, keys, macros and
  profiles), for as long as the app is open.
- **Update** on a saved profile replaces it with the current settings.
- The Keyboard tab is gone: the keyboard's details and access setup are in Settings, and the raw reads
  are under **Debug tools** at the bottom of Settings.
- A warning shows on every tab when the keyboard isn't connected by USB.

## 0.13.4 (2026-11-06)

- Removed the Features list from the Keyboard tab.

## 0.13.3 (2026-11-06)

- Scrolling over the colour sliders and the macro number boxes scrolls the page instead of changing the value.

## 0.13.2 (2026-11-06)

- **Recent colours:** the colour pickers show the last six colours you used, one click to reuse.

## 0.13.1 (2026-11-06)

- **Self define brightness** (0–4). The keyboard has no brightness for Self define, so the app dims the
  colours it sends; your painted colours are kept as they are.

## 0.13.0 (2026-11-06)

- **Self define:** paint every key its own colour on a picture of the keyboard, with the colour wheel, and send it.
  Profiles keep these colours too.

## 0.12.0 (2026-11-06)

First public release.

- Lighting: effect, brightness and speed for each effect, and the Fixed on colour with a colour wheel.
- Key remapping on a picture of the keyboard, including modifiers and keys not on the board (F13–F24).
- Macros with pauses and repeat modes, assigned to any key except Fn.
- Profiles: save, apply, export and import; `--apply-profile` for keyboard shortcuts.
- Self-contained AppImage that adds its own launcher entry.
- Light and dark themes, accent colours and three sizes.
