"""In-window colour picker: hue ring around a saturation/brightness square, RGB sliders, hex field."""

from __future__ import annotations

import colorsys
import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Gdk, Graphene, Gsk, Gtk  # noqa: E402


def rgba(r, g, b, a=1.0) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


# Keep and return the object that owns the memory: init() returns a second wrapper around the
# same struct, which dangles once the original is garbage-collected.
def rect(x, y, w, h) -> Graphene.Rect:
    r = Graphene.Rect()
    r.init(x, y, w, h)
    return r


def point(x, y) -> Graphene.Point:
    p = Graphene.Point()
    p.init(x, y)
    return p


def rounded(x, y, w, h, radius) -> Gsk.RoundedRect:
    rr = Gsk.RoundedRect()
    rr.init_from_rect(rect(x, y, w, h), radius)
    return rr


def circle(cx, cy, r) -> Gsk.RoundedRect:
    return rounded(cx - r, cy - r, 2 * r, 2 * r, r)


def stops(*pairs):
    out = []
    for offset, colour in pairs:
        st = Gsk.ColorStop()
        st.offset, st.color = offset, colour
        out.append(st)
    return out


def to_hex(rgb) -> str:
    return "".join(f"{c:02x}" for c in rgb)


def parse_hex(text: str):
    t = text.strip().lstrip("#")
    if len(t) == 3:
        t = "".join(c * 2 for c in t)
    if len(t) != 6:
        raise ValueError
    v = bytes.fromhex(t)
    return v[0], v[1], v[2]


class HueSquare(Gtk.Widget):
    """A hue ring with a saturation (x) / brightness (y) square inside it."""

    RING = 0.16      # ring thickness as a fraction of the size
    SIZE = 220

    def __init__(self, on_change):
        super().__init__(focusable=True)
        self.on_change = on_change
        self.h, self.s, self.v = 0.0, 1.0, 1.0
        self._grab = None
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", lambda *_: setattr(self, "_grab", None))
        self.add_controller(drag)
        self._start = (0, 0)
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             ["Colour wheel. Use the sliders or the hex field for exact values"])

    def do_measure(self, orientation, for_size):
        return self.SIZE, self.SIZE, -1, -1

    def set_hsv(self, h, s, v):
        self.h, self.s, self.v = h, s, v
        self.queue_draw()

    def _geometry(self):
        w, h = self.get_width(), self.get_height()
        size = min(w, h)
        cx, cy = w / 2, h / 2
        outer = size / 2 - 2
        inner = outer * (1 - self.RING * 2)
        half = inner / math.sqrt(2) - 3
        return cx, cy, outer, inner, half

    def _background(self) -> Gdk.RGBA:
        ok, colour = self.get_style_context().lookup_color("SURFACE_CONTAINER")
        return colour if ok else rgba(0.5, 0.5, 0.5)

    def do_snapshot(self, snap):
        cx, cy, outer, inner, half = self._geometry()
        # hue ring: a conic gradient in a disc, with the middle painted over in the card colour
        snap.push_rounded_clip(circle(cx, cy, outer))
        hues = [(i / 6, rgba(*colorsys.hsv_to_rgb(i / 6, 1, 1))) for i in range(7)]
        snap.append_conic_gradient(rect(cx - outer, cy - outer, 2 * outer, 2 * outer),
                                   point(cx, cy), 90, stops(*hues))
        snap.pop()
        snap.push_rounded_clip(circle(cx, cy, inner))
        snap.append_color(self._background(), rect(cx - inner, cy - inner, 2 * inner, 2 * inner))
        snap.pop()
        # square: hue, white fading in from the left, black fading in towards the bottom
        x0, y0, side = cx - half, cy - half, 2 * half
        box = rect(x0, y0, side, side)
        snap.append_color(rgba(*colorsys.hsv_to_rgb(self.h, 1, 1)), box)
        snap.append_linear_gradient(box, point(x0, y0), point(x0 + side, y0),
                                    stops((0, rgba(1, 1, 1, 1)), (1, rgba(1, 1, 1, 0))))
        snap.append_linear_gradient(box, point(x0, y0), point(x0, y0 + side),
                                    stops((0, rgba(0, 0, 0, 0)), (1, rgba(0, 0, 0, 1))))
        # markers
        a = self.h * 2 * math.pi
        rm = (outer + inner) / 2
        self._marker(snap, cx + rm * math.cos(a), cy + rm * math.sin(a))
        self._marker(snap, x0 + side * self.s, y0 + side * (1 - self.v))

    @staticmethod
    def _marker(snap, x, y):
        snap.append_border(circle(x, y, 8), [3, 3, 3, 3], [rgba(0, 0, 0)] * 4)
        snap.append_border(circle(x, y, 6.5), [2, 2, 2, 2], [rgba(1, 1, 1)] * 4)

    def _begin(self, gesture, x, y):
        self._start = (x, y)
        cx, cy, outer, inner, half = self._geometry()
        d = math.hypot(x - cx, y - cy)
        if inner - 2 <= d <= outer + 2:
            self._grab = "ring"
        elif abs(x - cx) <= half + 4 and abs(y - cy) <= half + 4:
            self._grab = "square"
        else:
            self._grab = None
        self._apply(x, y)

    def _update(self, gesture, dx, dy):
        self._apply(self._start[0] + dx, self._start[1] + dy)

    def _apply(self, x, y):
        cx, cy, outer, inner, half = self._geometry()
        if self._grab == "ring":
            self.h = (math.atan2(y - cy, x - cx) / (2 * math.pi)) % 1.0
        elif self._grab == "square":
            self.s = min(1, max(0, (x - (cx - half)) / (2 * half)))
            self.v = min(1, max(0, 1 - (y - (cy - half)) / (2 * half)))
        else:
            return
        self.queue_draw()
        self.on_change(self.h, self.s, self.v)


class ColourPicker(Gtk.Box):
    """Wheel + square, R/G/B sliders, hex field and a preview. Calls on_apply(rgb) on Apply."""

    def __init__(self, rgb, on_apply, apply_label="Apply colour", on_change=None, recent=()):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        self.on_apply = on_apply
        self.on_change = on_change
        self.rgb = tuple(rgb)
        self._syncing = False
        self.wheel = HueSquare(self._from_wheel)
        self.wheel.set_valign(Gtk.Align.START)
        self.append(self.wheel)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, hexpand=True)
        self.scales = []
        for i, name in enumerate(("Red", "Green", "Blue")):
            row = Gtk.Box(spacing=10)
            lbl = Gtk.Label(label=name, xalign=0, width_chars=6)
            lbl.add_css_class("dim")
            row.append(lbl)
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 255, 1)
            sc.set_hexpand(True)
            sc.set_draw_value(True)
            sc.set_value_pos(Gtk.PositionType.RIGHT)
            sc.set_digits(0)
            sc.update_property([Gtk.AccessibleProperty.LABEL], [f"{name}, 0 to 255"])
            sc.connect("value-changed", self._from_scales)
            row.append(sc)
            right.append(row)
            self.scales.append(sc)

        row = Gtk.Box(spacing=10)
        lbl = Gtk.Label(label="Hex", xalign=0, width_chars=6)
        lbl.add_css_class("dim")
        row.append(lbl)
        self.hex = Gtk.Entry(max_length=7, width_chars=9)
        self.hex.add_css_class("colour-entry")
        self.hex.update_property([Gtk.AccessibleProperty.LABEL], ["Colour as a hex code"])
        self.hex.connect("changed", self._from_hex)
        self.hex.connect("activate", lambda *_: self.on_apply(self.rgb))
        row.append(self.hex)
        self.preview = Swatch(self)
        self.preview.set_valign(Gtk.Align.CENTER)
        row.append(self.preview)
        right.append(row)

        if recent:
            row = Gtk.Box(spacing=8)
            lbl = Gtk.Label(label="Recent", xalign=0, width_chars=6)
            lbl.add_css_class("dim")
            row.append(lbl)
            for colour in list(recent)[:6]:
                b = Gtk.Button(tooltip_text="#" + to_hex(colour), valign=Gtk.Align.CENTER)
                b.add_css_class("recent-colour")
                fill = KeyColour(colour)
                fill.set_size_request(24, 24)
                b.set_child(fill)
                b.update_property([Gtk.AccessibleProperty.LABEL], [f"Use recent colour #{to_hex(colour)}"])
                b.connect("clicked", lambda *_, c=tuple(colour): self.set_rgb(c, "recent"))
                row.append(b)
            right.append(row)

        self.apply_btn = Gtk.Button(label=apply_label)
        self.apply_btn.add_css_class("filled")
        self.apply_btn.set_halign(Gtk.Align.START)
        self.apply_btn.connect("clicked", lambda *_: self.on_apply(self.rgb))
        right.append(self.apply_btn)
        self.append(right)
        self.set_rgb(self.rgb)

    def set_sensitive_apply(self, ok):
        self.apply_btn.set_sensitive(ok)

    def set_rgb(self, rgb, source=None):
        self.rgb = tuple(int(c) for c in rgb)
        self._syncing = True
        try:
            if source != "scales":
                for sc, c in zip(self.scales, self.rgb):
                    sc.set_value(c)
            if source != "hex":
                self.hex.set_text("#" + to_hex(self.rgb))
            if source != "wheel":
                h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in self.rgb))
                if s == 0 or v == 0:
                    h = self.wheel.h          # keep the hue the user had when the colour is grey/black
                self.wheel.set_hsv(h, s, v)
        finally:
            self._syncing = False
        self.preview.queue_draw()
        if self.on_change and source is not None:
            self.on_change(self.rgb)

    def _from_wheel(self, h, s, v):
        if not self._syncing:
            self.set_rgb([round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v)], "wheel")

    def _from_scales(self, *_):
        if not self._syncing:
            self.set_rgb([sc.get_value() for sc in self.scales], "scales")

    def _from_hex(self, entry):
        if self._syncing:
            return
        try:
            rgb = parse_hex(entry.get_text())
        except ValueError:
            return
        self.set_rgb(rgb, "hex")



class Swatch(Gtk.Widget):
    """Preview of the picker's colour, in true colour."""

    def __init__(self, picker):
        super().__init__()
        self.picker = picker

    def do_measure(self, orientation, for_size):
        n = 56 if orientation == Gtk.Orientation.HORIZONTAL else 32
        return n, n, -1, -1

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        snap.push_rounded_clip(rounded(0, 0, w, h, 8))
        snap.append_color(rgba(*(c / 255 for c in self.picker.rgb)), rect(0, 0, w, h))
        snap.pop()


class KeyColour(Gtk.Widget):
    """A rounded fill in a key's true colour (Self define editor)."""

    def __init__(self, rgb=(0, 0, 0)):
        super().__init__()
        self.rgb = tuple(rgb)

    def set_rgb(self, rgb):
        self.rgb = tuple(rgb)
        self.queue_draw()

    def do_measure(self, orientation, for_size):
        return 0, 0, -1, -1

    def do_snapshot(self, snap):
        w, h = self.get_width(), self.get_height()
        snap.push_rounded_clip(rounded(0, 0, w, h, 6))
        snap.append_color(rgba(*(c / 255 for c in self.rgb)), rect(0, 0, w, h))
        snap.pop()


def readable_on(rgb) -> str:
    """'dark' or 'light' text for a label drawn on this colour (luminance threshold 0.45)."""
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])
    return "dark" if lum > 0.45 else "light"
