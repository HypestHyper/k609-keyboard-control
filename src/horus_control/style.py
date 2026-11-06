"""Palette from one seed, and the app-owned stylesheet (GTK App Family baseline)."""

from __future__ import annotations

import colorsys
import re

SEED = "#4d7cff"   # default accent: lapis blue
# Accent choices (family seeds plus the app's own). Each generates the whole palette.
ACCENTS = (("Lapis", "4d7cff"), ("Mint", "53dbb0"), ("Sky", "6aa6ff"), ("Lilac", "b38cff"),
           ("Rose", "ff8fb1"), ("Amber", "ffb35c"), ("Leaf", "9ccc65"))
SCALES = {"compact": 0.8, "default": 0.9, "large": 1.0}
# Preset colours for the keyboard's Fixed on effect (true colours, never tinted).
SWATCHES = (("White", "ffffff"), ("Red", "ff0000"), ("Orange", "ff8000"), ("Yellow", "ffff00"),
            ("Green", "00ff00"), ("Cyan", "00ffff"), ("Blue", "0000ff"), ("Purple", "8000ff"),
            ("Pink", "ff00ff"))

# role: (sat, lightness) for dark, then light. "s" = seed saturation, "s.8" = seed sat x 0.8.
# "t" marks the tertiary hue (+0.17).
_ROLES = {
    "SURFACE_DIM": ((.14, .065), (.22, .955)),
    "SURFACE_CONTAINER_LOWEST": ((.14, .05), (.14, 1.0)),
    "SURFACE_CONTAINER_LOW": ((.14, .095), (.22, .97)),
    "SURFACE_CONTAINER": ((.14, .115), (.28, .985)),
    "SURFACE_CONTAINER_HIGH": ((.14, .15), (.22, .925)),
    "SURFACE_CONTAINER_HIGHEST": ((.14, .19), (.22, .895)),
    "SURFACE_BRIGHT": ((.14, .23), (.22, .87)),
    "PRIMARY": (("s", .66), ("s", .34)),
    "PRIMARY_HOVER": (("s", .74), ("s", .28)),
    "ON_PRIMARY": (("s", .12), ("s", .99)),
    "PRIMARY_CONTAINER": (("s.8", .24), ("s.8", .86)),
    "ON_PRIMARY_CONTAINER": (("s", .84), ("s", .14)),
    "SECONDARY_CONTAINER": ((.20, .26), (.28, .86)),
    "SECONDARY_CONTAINER_HOVER": ((.22, .31), (.28, .81)),
    "ON_SECONDARY_CONTAINER": ((.25, .88), (.30, .14)),
    "TERTIARY": (("t", .45, .72), ("t", .45, .40)),
    "TERTIARY_CONTAINER": (("t", .25, .28), ("t", .45, .89)),
    "ON_TERTIARY_CONTAINER": (("t", .35, .88), ("t", .40, .16)),
    "ON_SURFACE": ((.10, .90), (.12, .11)),
    "ON_SURFACE_VARIANT": ((.08, .76), (.08, .30)),
    "OUTLINE": ((.07, .57), (.07, .46)),
    "OUTLINE_VARIANT": ((.09, .27), (.10, .80)),
    "INVERSE_SURFACE": ((.10, .89), (.10, .19)),
    "INVERSE_ON_SURFACE": ((.12, .18), (.12, .94)),
}
_FIXED = {
    "ERROR": ("#ffb4ab", "#ba1a1a"),
    "ERROR_CONTAINER": ("#93000a", "#ffdad6"),
    "ON_ERROR_CONTAINER": ("#ffdad6", "#410002"),
}


def _hex(r, g, b) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(c * 255))) for c in (r, g, b)))


def palette(dark: bool, seed: str = SEED) -> dict[str, str]:
    r, g, b = (int(seed[i:i + 2], 16) / 255 for i in (1, 3, 5))
    hue, _, sat = colorsys.rgb_to_hls(r, g, b)
    sat = min(0.85, max(0.45, sat))
    out = {}
    for role, spec in _ROLES.items():
        spec = spec[0] if dark else spec[1]
        h = hue
        if spec[0] == "t":
            h = (hue + 0.17) % 1.0
            spec = spec[1:]
        s, light = spec
        s = sat if s == "s" else sat * 0.8 if s == "s.8" else s
        out[role] = _hex(*colorsys.hls_to_rgb(h, light, s))
    for role, (d, l) in _FIXED.items():
        out[role] = d if dark else l
    _fit_primary(out, hue, sat, dark)
    return out


def _fit_primary(out: dict, hue: float, sat: float, dark: bool) -> None:
    """Nudge PRIMARY's lightness until text on it and it on cards both reach 4.5:1.

    Pale seeds (mint, leaf) need a darker PRIMARY in the light theme, deep ones (lilac) a lighter
    one in the dark theme. Contrast is measured, never assumed (family design language, COL).
    """
    light = 0.66 if dark else 0.34
    step = 0.01 if dark else -0.01
    for _ in range(40):
        primary = _hex(*colorsys.hls_to_rgb(hue, light, sat))
        if (contrast(out["ON_PRIMARY"], primary) >= 4.5
                and contrast(primary, out["SURFACE_CONTAINER"]) >= 4.5
                and contrast(primary, out["SURFACE_DIM"]) >= 4.5):
            break
        light += step
    out["PRIMARY"] = primary
    out["PRIMARY_HOVER"] = _hex(*colorsys.hls_to_rgb(hue, min(0.95, max(0.05, light + (0.08 if dark else -0.06))), sat))


def luminance(hex_colour: str) -> float:
    def ch(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(hex_colour[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


_CSS = """
window.horus { background-color: @SURFACE_DIM; color: @ON_SURFACE; font-family: "Google Sans Flex", sans-serif; font-size: fpx(14)px; }
window.horus box, window.horus label { margin: 0; padding: 0; }
window.horus scrolledwindow, window.horus viewport { background: transparent; border: none; box-shadow: none; }
window.horus button label { font-size: inherit; }

.header { min-height: px(64)px; padding: 0 px(20)px; }
.app-icon { background-color: @PRIMARY_CONTAINER; color: @ON_PRIMARY_CONTAINER; border-radius: px(12)px; min-width: px(40)px; min-height: px(40)px; }
.app-title { font-size: fpx(24)px; font-weight: 700; }
.title { font-size: fpx(20)px; font-weight: 700; }
.heading { font-size: fpx(15)px; font-weight: 700; }
.small { font-size: fpx(13)px; }
.tiny { font-size: fpx(11.5)px; }
.dim { color: @ON_SURFACE_VARIANT; }
.faint { color: @OUTLINE; }
.mono { font-family: monospace; font-size: fpx(12.5)px; font-feature-settings: "tnum"; }
.error-text { color: @ERROR; }

window.horus button { border: none; box-shadow: none; transform: none; background-image: none; text-shadow: none; outline: none;
  min-height: px(40)px; padding: 0 px(18)px; border-radius: px(20)px; font-weight: 600;
  background-color: @SECONDARY_CONTAINER; color: @ON_SECONDARY_CONTAINER;
  transition: background-color 220ms cubic-bezier(0.2, 0, 0, 1), border-radius 200ms cubic-bezier(0.34, 1.36, 0.64, 1); }
window.horus button:hover { background-color: @SECONDARY_CONTAINER_HOVER; }
window.horus button:active { border-radius: px(10)px; }
window.horus button:focus-visible { outline: 2px solid @PRIMARY; outline-offset: 2px; }
window.horus button:disabled { opacity: 0.5; }
window.horus button.filled { background-color: @PRIMARY; color: @ON_PRIMARY; }
window.horus button.filled:hover { background-color: @PRIMARY_HOVER; }
window.horus button.text { background-color: transparent; color: @PRIMARY; padding: 0 px(12)px; }
window.horus button.text:hover { background-color: alpha(@ON_SURFACE, 0.08); }
window.horus button.circle { min-width: px(40)px; padding: 0; border-radius: px(20)px; }
window.horus button.circle:active { border-radius: px(12)px; }

window.horus button.swatch { min-width: px(40)px; min-height: px(40)px; padding: 0; border-radius: px(20)px; border: 2px solid @OUTLINE_VARIANT; }
window.horus button.swatch:active { border-radius: px(12)px; }
window.horus button.swatch.current { border-radius: px(12)px; outline: 3px solid @PRIMARY; outline-offset: 2px; }
.colour-entry { font-family: monospace; }

window.horus button.keycap { min-height: 0; min-width: 0; padding: 0 px(2)px; border-radius: px(8)px; font-size: fpx(12)px;
  background-color: @SURFACE_CONTAINER_HIGHEST; color: @ON_SURFACE; }
window.horus button.keycap:hover { background-color: @SURFACE_BRIGHT; }
window.horus button.keycap:active { border-radius: px(4)px; }
window.horus button.keycap:disabled { opacity: 0.45; }
window.horus button.keycap.remapped { background-color: @PRIMARY_CONTAINER; color: @ON_PRIMARY_CONTAINER; }
window.horus button.keycap.remapped:hover { background-color: @PRIMARY_CONTAINER; }
window.horus button.keycap.selected { outline: 2px solid @PRIMARY; outline-offset: 1px; }
window.horus.chooser { background-color: transparent; }
window.horus button.chooser-key { min-height: px(34)px; padding: 0 px(6)px; }
window.horus scale { padding: px(8)px 0; }
window.horus scale trough { min-height: px(6)px; border-radius: 999px; border: none; background-color: @SURFACE_CONTAINER_HIGHEST; background-image: none; box-shadow: none; outline: none; }
window.horus scale highlight { border-radius: 999px; background-color: @PRIMARY; background-image: none; border: none; }
window.horus scale slider { min-width: px(18)px; min-height: px(18)px; margin: -px(6)px; border-radius: 999px; border: none; box-shadow: none; background-image: none; background-color: @PRIMARY; }
window.horus scale:focus-visible slider { outline: 2px solid @PRIMARY; outline-offset: 2px; }
window.horus scale value { color: @ON_SURFACE_VARIANT; font-feature-settings: "tnum"; min-width: px(28)px; }
.keycap-sub { font-size: fpx(10.5)px; font-weight: 700; }

.tabbar { background-color: @SURFACE_CONTAINER_LOW; border-radius: px(24)px; padding: px(4)px; }
.tabbar button { background-color: transparent; color: @ON_SURFACE_VARIANT; }
.tabbar button:hover { background-color: alpha(@ON_SURFACE, 0.08); }
.tabbar button:checked { background-color: @SECONDARY_CONTAINER; color: @ON_SECONDARY_CONTAINER; border-radius: px(12)px; }

.group button { border-radius: px(6)px; padding: 0 px(16)px; }
.group button:first-child { border-top-left-radius: px(18)px; border-bottom-left-radius: px(18)px; }
.group button:last-child { border-top-right-radius: px(18)px; border-bottom-right-radius: px(18)px; }
.group button:checked { background-color: @PRIMARY; color: @ON_PRIMARY; border-radius: px(18)px; }

.card { background-color: @SURFACE_CONTAINER; border-radius: px(28)px; padding: px(20)px; }
.inner { background-color: @SURFACE_CONTAINER_HIGH; border-radius: px(20)px; padding: px(16)px; }
.divider { background-color: @OUTLINE_VARIANT; min-height: 1px; }

.chip { border-radius: 999px; padding: px(4)px px(12)px; font-size: fpx(13)px; font-weight: 600; }
.chip.ok { background-color: @PRIMARY_CONTAINER; color: @ON_PRIMARY_CONTAINER; }
.chip.warn { background-color: @TERTIARY_CONTAINER; color: @ON_TERTIARY_CONTAINER; }
.chip.error { background-color: @ERROR_CONTAINER; color: @ON_ERROR_CONTAINER; }
.chip.neutral { background-color: @SURFACE_CONTAINER_HIGHEST; color: @ON_SURFACE_VARIANT; }

window.horus switch { min-width: px(44)px; min-height: px(24)px; border-radius: px(16)px; border: 2px solid @OUTLINE; background-color: @SURFACE_CONTAINER_HIGHEST; background-image: none; box-shadow: none; outline: none;
  transition: background-color 250ms cubic-bezier(0.2, 0, 0, 1); }
window.horus switch:checked { background-color: @PRIMARY; border-color: @PRIMARY; }
window.horus switch:focus-visible { outline: 2px solid @PRIMARY; outline-offset: 2px; }
window.horus switch slider { min-width: px(16)px; min-height: px(16)px; margin: px(2)px; border-radius: 999px; background-color: @OUTLINE; border: none; box-shadow: none; background-image: none;
  transition: all 250ms cubic-bezier(0.34, 1.36, 0.64, 1); }
window.horus switch:checked slider { min-width: px(20)px; min-height: px(20)px; margin: 0; background-color: @ON_PRIMARY; }

window.horus expander-widget title, window.horus expander title { padding: px(6)px 0; }
window.horus expander-widget arrow, window.horus expander arrow { color: @ON_SURFACE_VARIANT; }
window.horus textview, window.horus textview text { background-color: transparent; color: @ON_SURFACE; }

window.horus entry { background-color: @SURFACE_CONTAINER_HIGHEST; color: @ON_SURFACE; border: none; box-shadow: none; outline: none; border-radius: px(12)px; min-height: px(38)px; padding: 0 px(12)px; background-image: none; }
window.horus entry:focus-within { outline: 2px solid @PRIMARY; outline-offset: -2px; }
window.horus entry > text > placeholder { color: @ON_SURFACE_VARIANT; }
window.horus dropdown > button { background-color: @SURFACE_CONTAINER_HIGHEST; color: @ON_SURFACE; border-radius: px(12)px; min-height: px(38)px; }
window.horus popover > contents { background-color: @SURFACE_CONTAINER_HIGH; color: @ON_SURFACE; border-radius: px(16)px; box-shadow: none; border: none; }
tooltip { background-color: @INVERSE_SURFACE; color: @INVERSE_ON_SURFACE; border-radius: 8px; box-shadow: none; border: none; }
tooltip * { color: @INVERSE_ON_SURFACE; }
"""


def _px(scale: float):
    def size(m):
        v = float(m.group(1))
        return str(int(v) if v <= 2 else max(1, round(v * scale)))
    return size


def _fpx(scale: float):
    def size(m):
        v = float(m.group(1))
        return str(max(10, round(v * (1 - (1 - scale) * 0.6))))
    return size


def stylesheet(dark: bool, size: str = "default", reduce_motion: bool = False, seed: str = SEED) -> str:
    scale = SCALES.get(size, 0.9)
    seed = "#" + seed.lstrip("#")
    colours = "\n".join(f"@define-color {k} {v};" for k, v in palette(dark, seed).items())
    # Component classes must outrank the theme-proofing resets on box/label.
    css = re.sub(r"(?m)^\.", "window.horus .", _CSS)
    css = re.sub(r"fpx\(([\d.]+)\)", _fpx(scale), css)
    css = re.sub(r"(?<![\w])px\(([\d.]+)\)", _px(scale), css)
    swatch_colours = {h for _, h in SWATCHES} | {h for _, h in ACCENTS} | {seed.lstrip("#").lower()}
    css += "\n" + "\n".join(f"window.horus button.swatch-{h}, window.horus button.swatch-{h}:hover "
                              f"{{ background-color: #{h}; }}" for h in sorted(swatch_colours))
    if reduce_motion:
        css += "\n* { transition: none; }\n"
    return colours + "\n" + css
