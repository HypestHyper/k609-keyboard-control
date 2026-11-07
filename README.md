<p align="center">
  <img alt="Keyboard Control" src="src/k609_control/resources/io.github.HypestHyper.K609KeyboardControl.svg" width="128">
</p>

<h1 align="center">Keyboard Control</h1>

<p align="center">
  Linux software for the <b>Redragon Horus SE K609</b> (K609GG) keyboard: RGB lighting, key remapping, macros and profiles, without Windows or Wine. A GTK 4 app, shipped as one AppImage that runs on most distributions.
</p>

<p align="center">
  <img alt="Version 0.14.0" src="https://img.shields.io/badge/version-0.14.0-4d7cff">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="Linux" src="https://img.shields.io/badge/platform-Linux-informational">
  <img alt="AppImage" src="https://img.shields.io/badge/package-AppImage-2b88d8">
  <img alt="GTK 4" src="https://img.shields.io/badge/GTK-4-4A86CF">
  <img alt="Material 3 Expressive" src="https://img.shields.io/badge/style-Material%203%20Expressive-8f7ae0">
</p>

<p align="center">
  <a href="#installation">Install</a> ·
  <a href="#features">Features</a> ·
  <a href="#keyboard-access">Keyboard access</a> ·
  <a href="#command-line">Command line</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

> **AI disclosure:** This project was written almost entirely by an AI assistant, with direction and testing by the author. It has been tested on CachyOS (Arch Linux) with Hyprland and one Horus SE K609GG, so review the code before relying on it.

> **Unofficial:** not affiliated with or endorsed by Redragon. It talks to the keyboard the same way Redragon's Windows software does, using commands recorded from that software. Trademarks belong to their owners.

## Features

- **Lighting:** all 18 effects, brightness and speed for each effect, and the Fixed on colour with a colour wheel, RGB sliders and hex entry.
- **Per-key RGB (Self define):** paint each key its own colour on a picture of the keyboard.
- **Key remapping:** click a key on a picture of the keyboard and choose what it sends: letters, F1–F24, navigation keys, modifiers (Caps Lock to Ctrl), or a macro. Fn stays locked so you can't lose its shortcuts.
- **Macros:** key presses and releases with pauses, repeated a number of times or while held, stored in the keyboard.
- **Profiles:** save lighting, keys and macros together, switch with one click or a keyboard shortcut, and export or import them as files.
- Everything is saved **in the keyboard**, so it keeps working on any computer, with nothing running in the background.
- Light and dark themes, accent colours, three sizes, keyboard navigation and screen reader labels.

## Compatible keyboards

| Keyboard | USB ID | Connection |
| --- | --- | --- |
| Redragon Horus SE K609 / K609GG / K609 RGB PRO | `258a:0049` (BY Tech Gaming Keyboard) | Wired USB |

The 2.4 GHz receiver and Bluetooth aren't supported. Other keyboards with the same USB ID may use a different layout: the app checks the keyboard's data and refuses to write if it doesn't match.

## Installation

1. Download `K609_Keyboard_Control-…-x86_64.AppImage` from [Releases](../../releases/latest).
2. Make it executable and start it:

   ```sh
   chmod +x K609_Keyboard_Control-*-x86_64.AppImage
   ./K609_Keyboard_Control-*-x86_64.AppImage
   ```

The first start adds **Keyboard Control** to your app launcher. It bundles Python and GTK 4, so nothing else needs installing; distributions from about 2022 on are supported (Ubuntu 22.04+, Debian 12, Fedora, Arch, openSUSE, Mint 21+). If it won't start, install FUSE 2 (`sudo pacman -S fuse2`, `sudo apt install libfuse2`, `sudo dnf install fuse`), or run it with `--appimage-extract-and-run`.

## Keyboard access

Linux only lets root open the keyboard's settings channel. The app shows the commands to allow your user once; they install this udev rule, which covers only this keyboard's settings interface, never its typing interface:

```sh
printf '%s\n' '# Keyboard Control: let the logged-in user open the K609GG configuration interface.' '# Wired USB 258a:0049, HID interface 1 only. Typing interface 0 is left alone.' 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="258a", ATTRS{idProduct}=="0049", ENV{HORUS_K609GG}="1"' 'SUBSYSTEM=="hidraw", ENV{HORUS_K609GG}=="1", ATTRS{bInterfaceNumber}=="01", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-horus-control.rules > /dev/null
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw
```

Then unplug and reconnect the keyboard. The rule is also in [`packaging/70-horus-control.rules`](packaging/70-horus-control.rules). The app never reads what you type.

## Command line

```sh
K609_Keyboard_Control.AppImage --apply-profile Gaming   # apply a saved profile, then exit
K609_Keyboard_Control.AppImage --list-profiles
K609_Keyboard_Control.AppImage --inspect                # show the detected keyboard
```

To switch profiles from the keyboard, remap a spare key to F13–F24 and bind it in your desktop. In Hyprland:

```
bind = , F13, exec, ~/Applications/K609_Keyboard_Control.AppImage --apply-profile "Gaming"
```

## Files

| What | Where |
| --- | --- |
| Settings, macros, profiles | `~/.config/k609-keyboard-control/` |
| Launcher entry and icon | `~/.local/share/applications/`, `~/.local/share/icons/` |

## Development

```sh
PYTHONPATH=src python3 -m k609_control    # run from the source folder (needs GTK 4 and PyGObject)
python3 -m pytest                         # tests use fake keyboards, never a real one
sh tools/build-appimage.sh                # build the AppImage (Ubuntu 22.04, or podman/docker)
```

How the keyboard protocol was worked out, byte by byte: [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

MIT, see [LICENSE](LICENSE).
