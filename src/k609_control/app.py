"""Keyboard Control GTK 4 window. Never touches HID directly; uses device/hidraw helpers off the main thread."""

from __future__ import annotations

import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, capabilities, keymap, lighting, macros, profiles, selfdefine, settings as settings_mod  # noqa: E402
from .device import CONFIG_INTERFACE, UDEV_RULE, Keyboard, find_keyboards  # noqa: E402
from .hidraw import (AccessDenied, DeviceGone, Handle, WriteFailed, describe_diff, describe_keymap_diff,
                     diff_blocks, hexdump, read_keymap_block, read_lighting_block)  # noqa: E402
from .colourpicker import ColourPicker, KeyColour, readable_on  # noqa: E402
from .style import stylesheet  # noqa: E402

from . import APP_ID, APP_NAME, COMMENT, desktop  # noqa: E402
SCAN_SECONDS = 2
RULE_PATH = "/etc/udev/rules.d/70-horus-control.rules"


def label(text="", *classes, xalign=0.0, wrap=True, selectable=False) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    if wrap:
        lbl.set_wrap_mode(2)  # Pango.WrapMode.WORD_CHAR
    for c in classes:
        lbl.add_css_class(c)
    return lbl


def vbox(spacing=0, *classes) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in classes:
        box.add_css_class(c)
    return box


def hbox(spacing=0, *classes) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in classes:
        box.add_css_class(c)
    return box


def chip(text, kind, icon=None) -> Gtk.Box:
    box = hbox(6, "chip", kind)
    if icon:
        box.append(Gtk.Image.new_from_icon_name(icon))
    box.append(label(text, wrap=False))
    return box


def set_accessible_label(widget, text):
    widget.update_property([Gtk.AccessibleProperty.LABEL], [text])


def icon_button(icon, tooltip, callback) -> Gtk.Button:
    btn = Gtk.Button(icon_name=icon, tooltip_text=tooltip)
    btn.add_css_class("circle")
    set_accessible_label(btn, tooltip)
    btn.connect("clicked", lambda *_: callback())
    return btn


def section(title, explanation) -> Gtk.Box:
    box = vbox(4)
    box.set_margin_top(18)
    box.append(label(title, "title"))
    if explanation:
        box.append(label(explanation, "small", "dim"))
    return box


def clear(box: Gtk.Box):
    while (child := box.get_first_child()) is not None:
        box.remove(child)


class Clamp(Gtk.Widget):
    """Centres one child and caps its width, for a readable line length on wide windows."""

    def __init__(self, child, max_width):
        super().__init__(hexpand=True)
        self.max_width = max_width
        child.set_parent(self)
        self.child = child

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.VERTICAL and for_size >= 0:
            for_size = min(for_size, self.max_width)
        m, n, _, _ = self.child.measure(orientation, for_size)
        if orientation == Gtk.Orientation.HORIZONTAL:
            n = min(max(m, n), max(m, self.max_width))
        return m, n, -1, -1

    def do_size_allocate(self, width, height, baseline):
        w = max(self.child.measure(Gtk.Orientation.HORIZONTAL, -1)[0], min(width, self.max_width))
        alloc = Gdk.Rectangle()
        alloc.x, alloc.y, alloc.width, alloc.height = (width - w) // 2, 0, w, height
        self.child.size_allocate(alloc, -1)

    def do_dispose(self):
        if self.child is not None:
            self.child.unparent()
            self.child = None
        Gtk.Widget.do_dispose(self)


class KeyboardView(Gtk.Widget):
    """Places key buttons at their real positions (official layout), scaled to the width."""

    X0, Y0, W, H = 16, 54, 599, 187

    def __init__(self):
        super().__init__(hexpand=True)
        self.keys = []

    def set_keys(self, keys):  # keys: list of (button, (x1, y1, x2, y2))
        for button, _ in self.keys:
            button.unparent()
        self.keys = keys
        for button, _ in keys:
            button.set_parent(self)
        self.queue_resize()

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 470, 740, -1, -1
        width = for_size if for_size > 0 else 740
        h = round(self.H * width / self.W)
        return h, h, -1, -1

    def do_size_allocate(self, width, height, baseline):
        scale = width / self.W
        gap = max(1, round(3 * scale))
        for button, (x1, y1, x2, y2) in self.keys:
            # Cfg.ini draws small keys with wide gaps; grow each key towards its neighbours.
            x2, y2 = min(x2 + 9, self.X0 + self.W), min(y2 + 9, self.Y0 + self.H)
            button.measure(Gtk.Orientation.HORIZONTAL, -1)
            button.measure(Gtk.Orientation.VERTICAL, -1)
            r = Gdk.Rectangle()
            r.x = round((x1 - self.X0) * scale)
            r.y = round((y1 - self.Y0) * scale)
            r.width = max(1, round((x2 - self.X0) * scale) - r.x - gap)
            r.height = max(1, round((y2 - self.Y0) * scale) - r.y - gap)
            button.size_allocate(r, -1)



class KeyChooser(Gtk.Window):
    """Pick a key by clicking it on the keyboard layout, or one of the keys that aren't on the board.

    on_pick(kind, value): kind "code" (a USB key code) or "macro" (index into macros).
    """

    def __init__(self, parent, title, current, on_pick, macro_names=None, current_macro=None):
        super().__init__(transient_for=parent, modal=True, decorated=False, title=title)
        self.add_css_class("horus")
        self.add_css_class("chooser")
        self.set_default_size(800, -1)
        self.on_pick = on_pick
        root = vbox(14, "card")
        root.set_margin_start(4)
        root.set_margin_end(4)
        root.set_margin_top(4)
        root.set_margin_bottom(4)
        self.set_child(root)
        root.append(label(title, "title"))
        root.append(label("Click a key. Escape cancels.", "small", "dim"))

        defaults = {k.number: k for k in keymap.KEYS}
        buttons = []
        for number, rect in keymap.LAYOUT.items():
            k = defaults.get(number)
            name = k.name if k else keymap.SPECIAL[number]
            btn = Gtk.Button()
            btn.add_css_class("keycap")
            btn.set_child(label(keymap.CAP_LABELS.get(name, name) if k else name, xalign=0.5, wrap=False))
            if k is None:
                btn.set_sensitive(False)
            else:
                code = k.default
                btn.set_tooltip_text(keymap.TARGETS.get(code, name))
                set_accessible_label(btn, keymap.TARGETS.get(code, name))
                if code == current and current_macro is None:
                    btn.add_css_class("selected")
                btn.connect("clicked", lambda *_, c=code: self._pick("code", c))
            buttons.append((btn, rect))
        self.view = KeyboardView()
        self.view.set_keys(buttons)
        root.append(self.view)

        on_board = {k.default for k in keymap.KEYS}
        extras = [c for c in keymap.TARGETS if c not in on_board]
        root.append(label("Keys not on this keyboard", "heading"))
        root.append(self._button_grid([(keymap.SHORT_TARGETS.get(keymap.TARGETS[c], keymap.TARGETS[c]),
                                        keymap.TARGETS[c], ("code", c), c == current and current_macro is None)
                                       for c in extras]))
        if macro_names:
            root.append(label("Macros", "heading"))
            root.append(self._button_grid([(n, f"Macro “{n}”", ("macro", i), i == current_macro)
                                           for i, n in enumerate(macro_names)]))
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("text")
        cancel.set_halign(Gtk.Align.END)
        cancel.connect("clicked", lambda *_: self.close())
        root.append(cancel)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, _k, _s: (self.close(), True)[1] if kv == Gdk.KEY_Escape else False)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: (self.view.set_keys([]), False)[1])

    def _button_grid(self, items) -> Gtk.Widget:
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=12,
                           min_children_per_line=4, column_spacing=6, row_spacing=6, homogeneous=True)
        for text, tip, pick, selected in items:
            b = Gtk.Button(label=text, tooltip_text=tip)
            b.add_css_class("keycap")
            b.add_css_class("chooser-key")
            set_accessible_label(b, tip)
            if selected:
                b.add_css_class("selected")
            b.connect("clicked", lambda *_, p=pick: self._pick(*p))
            flow.append(b)
        return flow

    def _pick(self, kind, value):
        self.close()
        self.on_pick(kind, value)


class Window(Gtk.ApplicationWindow):
    def __init__(self, app: "App"):
        super().__init__(application=app, title=APP_NAME)
        self.app = app
        self.add_css_class("horus")
        self.set_default_size(820, 760)

        self.keyboards: list[Keyboard] = []
        self.selected: str | None = None       # usb_path of the chosen keyboard
        self.scan_running = False
        self.scan_signature = None
        self.reading = False
        self.feature_results = None             # (devnode, results) or None
        self.feature_message = ""
        self.previous_block = None              # (devnode, mode, bytes) of the last good read
        self.read_mode = "lighting"             # what the Keyboard tab reads: "lighting" or "keymap"
        self.last_change = None                 # None = first read, "" = no change, else text
        self.change_log: list[str] = []
        self.pending_note = ""
        self.note_entry = Gtk.Entry(placeholder_text="What did you just pick? For example: Wave", hexpand=True)
        set_accessible_label(self.note_entry, "Name of the setting you just picked")
        self.note_entry.connect("activate", lambda *_: self._read_current())

        root = vbox()
        self.set_child(root)

        # Header
        header = hbox(12, "header")
        icon = Gtk.Image.new_from_file(desktop.ICON_SOURCE)
        icon.set_pixel_size(48)
        icon.set_valign(Gtk.Align.CENTER)
        header.append(icon)
        header.append(label(APP_NAME, "app-title", wrap=False))
        header.append(Gtk.Box(hexpand=True))
        self.status_holder = hbox()
        self.status_holder.set_valign(Gtk.Align.CENTER)
        header.append(self.status_holder)
        refresh = icon_button("view-refresh-symbolic", "Check for the keyboard now", self.scan)
        refresh.set_valign(Gtk.Align.CENTER)
        header.append(refresh)
        root.append(header)

        # Tabs
        self.stack = Gtk.Stack(vexpand=True)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(180)
        tabbar = hbox(4, "tabbar")
        tabbar.set_halign(Gtk.Align.START)
        tabbar.set_margin_start(20)
        tabbar.set_margin_bottom(6)
        self.tabs = []
        for i, (name, title, icon_name) in enumerate((
                ("keyboard", "Keyboard", "input-keyboard-symbolic"),
                ("lighting", "Lighting", "display-brightness-symbolic"),
                ("keys", "Keys", "input-keyboard-symbolic"),
                ("macros", "Macros", "media-record-symbolic"),
                ("profiles", "Profiles", "document-save-symbolic"),
                ("settings", "Settings", "preferences-system-symbolic"))):
            btn = Gtk.ToggleButton(tooltip_text=f"{title} (Alt+{i + 1})")
            inner = hbox(8)
            inner.append(Gtk.Image.new_from_icon_name(icon_name))
            inner.append(label(title, wrap=False))
            btn.set_child(inner)
            set_accessible_label(btn, title)
            if self.tabs:
                btn.set_group(self.tabs[0])
            btn.connect("toggled", self._on_tab, name)
            tabbar.append(btn)
            self.tabs.append(btn)
        root.append(tabbar)
        root.append(self.stack)

        self.keyboard_page = self._page("keyboard")
        self.lighting_page = self._page("lighting")
        self.keys_page = self._page("keys")
        self.keys_state = None                  # (devnode, {key name: code}) once loaded
        self.keys_busy = False
        self.keys_message = ("", "dim")
        self.keys_selected = keymap.REMAPPABLE[0].name
        self.keyboard_view = KeyboardView()     # kept for the window's life; its keys are replaced
        self.macros_page = self._page("macros")
        self.macro_list = macros.load()
        self.editing = None                     # (index or None for new, working copy) while editing
        self.profiles_page = self._page("profiles")
        self.profile_busy = False
        self.profile_message = ("", "dim")
        self.profile_name = Gtk.Entry(placeholder_text="Profile name, for example Gaming", hexpand=True)
        set_accessible_label(self.profile_name, "Name for the new profile")
        self.profile_name.connect("activate", lambda *_: self._save_profile(self._iface()))
        self.light_state = None                 # (devnode, lighting.State) once loaded
        self.handle = Handle()                  # kept open between operations, like the official software
        self.connect("close-request", lambda *_: (self.handle.close(), False)[1])
        self.light_busy = False
        self.light_message = ("", "dim")
        self.picker_rgb = None                  # colour shown in the Fixed on colour picker
        self.autoloaded = {}                    # tab -> devnode already read automatically
        self.selfdef, self.selfdef_brightness = selfdefine.load_all()   # key colours as painted, and 0-4
        self.selfdef_dirty = False
        self.paint_rgb = (255, 255, 255)
        self.selfdef_view = KeyboardView()
        self.settings_page = self._page("settings")
        self._build_settings()
        self.tabs[0].set_active(True)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        self.render()
        self.scan()
        GLib.timeout_add_seconds(SCAN_SECONDS, self._tick)

    # --- layout helpers -----------------------------------------------------

    def _page(self, name) -> Gtk.Box:
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        content = vbox(14)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_margin_bottom(28)
        scroller.set_child(Clamp(content, 880))
        self.stack.add_named(scroller, name)
        return content

    def _on_tab(self, button, name):
        if button.get_active():
            self.stack.set_visible_child_name(name)
            GLib.idle_add(lambda: (self._autoload(), False)[1])

    def _autoload(self):
        """Read the keyboard when the Lighting or Keys tab is shown and nothing is loaded yet.

        Tries once per tab and keyboard node, so a failing read isn't repeated on every redraw; the
        Load button stays as a fallback.
        """
        tab = self.stack.get_visible_child_name()
        iface = self._iface()
        if iface is None or not iface.access:
            return
        if tab == "lighting" and self.light_state is None and not self.light_busy:
            if self.autoloaded.get("lighting") != iface.devnode:
                self.autoloaded["lighting"] = iface.devnode
                self._light_run(lambda: lighting.read_state(iface.devnode, handle=self.handle), lambda st: "")
        elif tab == "keys" and self.keys_state is None and not self.keys_busy:
            if self.autoloaded.get("keys") != iface.devnode:
                self.autoloaded["keys"] = iface.devnode
                self._keys_run(lambda: keymap.read(iface.devnode, handle=self.handle), lambda cur: "")

    def _on_key(self, _ctrl, keyval, _code, state):
        if state & Gdk.ModifierType.ALT_MASK and Gdk.KEY_1 <= keyval <= Gdk.KEY_9:
            i = keyval - Gdk.KEY_1
            if i < len(self.tabs):
                self.tabs[i].set_active(True)
                return True
        if keyval == Gdk.KEY_F5 or (state & Gdk.ModifierType.CONTROL_MASK and keyval == Gdk.KEY_r):
            self.scan()
            return True
        return False

    # --- scanning (worker thread -> main loop) ------------------------------

    def _tick(self):
        self.scan()
        return True

    def scan(self):
        if self.scan_running:
            return
        self.scan_running = True

        def work():
            try:
                result = find_keyboards(os.environ.get("K609_SYSFS", "/sys"))
            except Exception as e:  # sysfs oddities must never crash the UI
                result = e
            GLib.idle_add(self._scan_done, result)
        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, result):
        self.scan_running = False
        if isinstance(result, Exception):
            result = []
        signature = tuple((k.usb_path, tuple((i.name, i.access) for i in k.interfaces)) for k in result)
        if signature == self.scan_signature:
            return False
        self.scan_signature = signature
        self.keyboards = result
        paths = [k.usb_path for k in result]
        if self.selected not in paths:
            self.selected = paths[0] if len(paths) == 1 else None
        kb = self.current()
        iface = kb.config_interface if kb else None
        if self.feature_results and (not iface or self.feature_results[0] != iface.devnode):
            self.feature_results = None
            self.feature_message = ""
        # Drop a handle on a keyboard that went away or changed node (off the main thread: it
        # waits for any operation in progress).
        keep = iface.devnode if iface and iface.access else None
        threading.Thread(target=self.handle.close, kwargs={"unless": keep}, daemon=True).start()
        self.render()
        if keep is None:
            self.autoloaded.clear()             # read again after a reconnect
        GLib.idle_add(lambda: (self._autoload(), False)[1])
        return False

    def current(self) -> Keyboard | None:
        for k in self.keyboards:
            if k.usb_path == self.selected:
                return k
        return None

    # --- rendering ------------------------------------------------------------

    def render(self):
        kb = self.current()
        iface = kb.config_interface if kb else None
        self.render_lighting(iface)
        self.render_keys(iface)
        self.render_macros(iface)
        self.render_profiles(iface)
        clear(self.status_holder)
        if not self.keyboards:
            self.status_holder.append(chip("Not found", "neutral", "dialog-information-symbolic"))
        elif kb is None:
            self.status_holder.append(chip(f"{len(self.keyboards)} keyboards", "warn", "dialog-warning-symbolic"))
        elif iface is None:
            self.status_holder.append(chip("Unexpected interfaces", "warn", "dialog-warning-symbolic"))
        elif not iface.access:
            self.status_holder.append(chip("No access", "warn", "dialog-warning-symbolic"))
        else:
            self.status_holder.append(chip("Connected", "ok", "emblem-ok-symbolic"))

        page = self.keyboard_page
        clear(page)
        if not self.keyboards:
            page.append(self._empty())
            return
        if len(self.keyboards) > 1:
            page.append(self._chooser())
        if kb is None:
            return
        page.append(section("Connection", "The wired keyboard as Linux sees it."))
        page.append(self._identity_card(kb, iface))
        if iface is None:
            return
        if not iface.access:
            page.append(self._access_card(iface))
        page.append(section("Read from the keyboard", "Reads the lighting settings or the key map the same "
                                                      "way Redragon's software does. Nothing is changed."))
        page.append(self._reports_card(iface))
        page.append(section("Features", "Controls appear here only after they are proven to work "
                                        "on this keyboard."))
        page.append(self._features_card())

    def _empty(self) -> Gtk.Widget:
        box = vbox(8)
        box.set_margin_top(80)
        box.set_halign(Gtk.Align.CENTER)
        img = Gtk.Image.new_from_icon_name("input-keyboard-symbolic")
        img.set_pixel_size(64)
        img.add_css_class("faint")
        box.append(img)
        box.append(label("Keyboard not found", "title", xalign=0.5))
        box.append(label("Connect the Horus SE K609GG with its USB cable. The app checks "
                         "again every few seconds. The 2.4 GHz receiver and Bluetooth are not supported.",
                         "dim", xalign=0.5))
        return box

    def _chooser(self) -> Gtk.Widget:
        box = vbox(8, "card")
        box.set_margin_top(18)
        box.append(label("More than one K609GG is connected", "heading"))
        box.append(label("Choose which keyboard to inspect.", "small", "dim"))
        names = ["Choose a keyboard…"] + [f"{k.label} · {k.usb_path.rsplit('/', 1)[-1]}" for k in self.keyboards]
        dd = Gtk.DropDown.new_from_strings(names)
        set_accessible_label(dd, "Keyboard to inspect")
        paths = [k.usb_path for k in self.keyboards]
        dd.set_selected(paths.index(self.selected) + 1 if self.selected in paths else 0)

        def chosen(*_):
            i = dd.get_selected()
            self.selected = paths[i - 1] if i > 0 else None
            self.feature_results = None
            self.feature_message = ""
            GLib.idle_add(lambda: (self.render(), False)[1])
        dd.connect("notify::selected", chosen)
        box.append(dd)
        return box

    def _row(self, grid, row, name, value, mono=False):
        grid.attach(label(name, "dim", wrap=False), 0, row, 1, 1)
        grid.attach(label(value or "—", *(["mono"] if mono else []), selectable=True), 1, row, 1, 1)

    def _identity_card(self, kb: Keyboard, iface) -> Gtk.Widget:
        card = vbox(12, "card")
        card.append(label(kb.label, "heading"))
        grid = Gtk.Grid(column_spacing=20, row_spacing=8)
        rows = [
            ("USB ID", f"{kb.vendor_id:04x}:{kb.product_id:04x}", True),
            ("Firmware (bcdDevice)", kb.bcd_device, True),
            ("USB version", kb.usb_version, False),
            ("HID interfaces", ", ".join(str(i.interface_number) for i in kb.interfaces), False),
        ]
        if iface:
            rows += [
                ("Configuration interface", f"Interface {iface.interface_number}", False),
                ("Device node", f"{iface.devnode} (diagnostics only; changes on reconnect)", True),
                ("Access", "Allowed for your user" if iface.access else "Denied: owned by root", False),
            ]
        for r, (n, v, m) in enumerate(rows):
            self._row(grid, r, n, v, m)
        card.append(grid)
        if iface is None:
            card.append(label(f"No HID interface {CONFIG_INTERFACE} with vendor feature reports was "
                              "found, so this may be a different keyboard revision. Nothing will be read.",
                              "small", "error-text"))
        card.append(label("The app never opens the typing interface (interface 0) and never "
                          "reads your keystrokes.", "small", "faint"))
        return card

    def _access_card(self, iface) -> Gtk.Widget:
        card = vbox(10, "card")
        card.append(label("Your user can't open the configuration interface", "heading"))
        card.append(label(f"{iface.devnode} is owned by root, so settings can't be read. You can allow "
                          "it yourself with a udev rule that covers only this keyboard's interface 1. "
                          "The app doesn't change system files.", "small", "dim"))
        quoted = " ".join(f"'{line}'" for line in UDEV_RULE.strip().splitlines())
        cmds = (f"printf '%s\\n' {quoted} | sudo tee {RULE_PATH} > /dev/null\n"
                "sudo udevadm control --reload\n"
                "sudo udevadm trigger --subsystem-match=hidraw")
        inner = vbox(8, "inner")
        inner.append(label("Paste these into a terminal (works in fish and bash), then unplug and "
                           "reconnect the keyboard:", "small"))
        inner.append(label(cmds, "mono", selectable=True))
        inner.append(Gtk.Box(css_classes=["divider"]))
        inner.append(label(f"To remove it later: sudo rm {RULE_PATH}", "mono", "dim", selectable=True))
        card.append(inner)
        copy = Gtk.Button(label="Copy commands")
        copy.set_halign(Gtk.Align.START)
        copy.connect("clicked", lambda *_: self._copy(cmds + "\n", copy))
        card.append(copy)
        return card

    def _reports_card(self, iface) -> Gtk.Widget:
        card = vbox(12, "card")
        desc = iface.descriptor
        grid = Gtk.Grid(column_spacing=20, row_spacing=6)
        for r, rep in enumerate(desc.reports):
            grid.attach(label(f"{rep.kind.capitalize()} 0x{rep.report_id:02x}", "mono", wrap=False), 0, r, 1, 1)
            grid.attach(label(f"{rep.payload_len} byte{'' if rep.payload_len == 1 else 's'}", "mono", "dim", wrap=False), 1, r, 1, 1)
        reports_grid = grid

        card.append(label("Pick and apply one thing in Redragon's software, type what you picked, then "
                          "press Enter. the app reads the keyboard and adds what changed to your "
                          "list.", "small", "dim"))
        card.append(self._group_row("Read", "Key map: remap one key at a time in Redragon's software, "
                                            "then type which key you changed.",
                                    [("lighting", "Lighting settings"), ("keymap", "Key map")],
                                    self.read_mode, self._set_read_mode))
        if (parent := self.note_entry.get_parent()) is not None:
            parent.remove(self.note_entry)
        self.note_entry.set_sensitive(iface.access)
        card.append(self.note_entry)
        row = hbox(12)
        read = Gtk.Button(label="Reading…" if self.reading else
                          ("Read key map" if self.read_mode == "keymap" else "Read lighting settings"))
        read.add_css_class("filled")
        read.set_sensitive(iface.access and not self.reading)
        read.set_tooltip_text("Sends the same read request as Redragon's software, then reads the "
                              "reply. Doesn't change any setting.")
        read.connect("clicked", lambda *_: self._read_current())
        row.append(read)
        if self.feature_message:
            msg = label(self.feature_message, "small", "dim")
            msg.set_valign(Gtk.Align.CENTER)
            msg.set_hexpand(True)
            row.append(msg)
        card.append(row)

        results = self.feature_results[1] if self.feature_results else None
        if results:
            for res in results:
                inner = vbox(6, "inner")
                head = hbox(8)
                title = "Key map" if res.data[:3] == bytes.fromhex("0684d8") else "Lighting settings"
                head.append(label(f"{title} · {len(res.data)} bytes", "heading", wrap=False))
                if res.ok:
                    head.append(chip("Read", "ok"))
                else:
                    head.append(chip("Problem", "error", "dialog-error-symbolic"))
                inner.append(head)
                if res.problem:
                    inner.append(label(res.problem, "small", "error-text"))
                is_keymap = res.data[:3] == bytes.fromhex("0684d8")
                if res.ok:
                    grid = Gtk.Grid(column_spacing=20, row_spacing=6)
                    if is_keymap:
                        self._row(grid, 0, "Caps Lock", "entry 143 (confirmed). Other keys not mapped yet")
                    else:
                        self._row(grid, 0, "Byte 21", f"0x{res.data[21]:02x}  ·  changes when the effect changes; "
                                  "effect names not known yet")
                        self._row(grid, 1, "Byte 20", f"0x{res.data[20]:02x}  ·  meaning not known yet")
                    inner.append(grid)
                    if self.last_change is None:
                        text = ("First read. Change one thing in Redragon's software, then read again "
                                "to see which bytes changed.")
                    elif not self.last_change:
                        text = "No change since the last read."
                    else:
                        text = f"Changed since the last read: {self.last_change}"
                    inner.append(label(text, "small", *([] if self.last_change else ["dim"])))
                if not is_keymap:
                    inner.append(label("Only bytes 20 and 21 have been seen to change. Everything else is "
                                       "unexplained so far.", "small", "faint"))
                if res.data:
                    exp = Gtk.Expander(label="Show bytes")
                    view = Gtk.TextView(editable=False, monospace=True, cursor_visible=False)
                    view.add_css_class("mono")
                    view.get_buffer().set_text(hexdump(res.data))
                    exp.set_child(view)
                    inner.append(exp)
                card.append(inner)
        if self.change_log:
            log = vbox(6, "inner")
            log.append(label("Your list", "heading"))
            for line in self.change_log:
                log.append(label(line, "mono", selectable=True))
            card.append(log)
        if results or self.change_log:
            btns = hbox(8)
            if self.change_log:
                copy_list = Gtk.Button(label="Copy list")
                copy_list.connect("clicked", lambda *_: self._copy("\n".join(self.change_log) + "\n", copy_list))
                btns.append(copy_list)
                clear_list = Gtk.Button(label="Clear list")
                clear_list.add_css_class("text")
                clear_list.set_tooltip_text("Empties the list. The keyboard isn't affected.")
                clear_list.connect("clicked", lambda *_: self._clear_log())
                btns.append(clear_list)
            copy = Gtk.Button(label="Copy diagnostics")
            copy.add_css_class("text")
            copy.connect("clicked", lambda *_: self._copy(self._diagnostics(), copy))
            btns.append(copy)
            card.append(btns)

        exp = Gtk.Expander(label="Report descriptor")
        details = vbox(10)
        details.append(reports_grid)
        details.append(label(" ".join(f"{b:02x}" for b in iface.descriptor_bytes), "mono", selectable=True))
        exp.set_child(details)
        card.append(exp)
        return card

    def _features_card(self) -> Gtk.Widget:
        card = vbox(10, "card")
        for i, cap in enumerate(capabilities.CAPABILITIES):
            if i:
                card.append(Gtk.Box(css_classes=["divider"]))
            row = hbox(12)
            text = vbox(2)
            text.set_hexpand(True)
            text.append(label(cap.title, "heading"))
            text.append(label(cap.evidence, "small", "dim"))
            row.append(text)
            usable = cap.status in (capabilities.Status.HARDWARE, capabilities.Status.HOST)
            where = {"remapping": "On the Keys tab", "macros": "On the Macros tab",
                     "profiles": "On the Profiles tab"}.get(cap.key, "On the Lighting tab")
            c = chip(where, "ok") if usable else chip("Not yet verified", "neutral")
            c.set_valign(Gtk.Align.CENTER)
            row.append(c)
            card.append(row)
        return card

    # --- actions ----------------------------------------------------------------

    def _read_current(self):
        kb = self.current()
        iface = kb.config_interface if kb else None
        if iface is not None and iface.access:
            self._read_features(iface)

    def _set_read_mode(self, mode):
        self.read_mode = mode
        self.feature_message = ""
        GLib.idle_add(lambda: (self.render(), False)[1])

    def _clear_log(self):
        self.change_log.clear()
        self.render()

    def _read_features(self, iface):
        if self.reading:
            return
        self.pending_note = self.note_entry.get_text().strip()
        self.reading = True
        self.feature_message = ""
        self.render()
        devnode = iface.devnode
        mode = self.read_mode
        reader = read_keymap_block if mode == "keymap" else read_lighting_block

        def work():
            try:
                res, msg = [reader(devnode, handle=self.handle)], ""
            except AccessDenied:
                res, msg = None, "Access denied. See the instructions above."
            except DeviceGone:
                res, msg = None, "The keyboard was disconnected during the read."
            except OSError as e:
                res, msg = None, f"Couldn't open {devnode}: {e.strerror}."
            GLib.idle_add(self._read_done, devnode, res, msg, mode)
        threading.Thread(target=work, daemon=True).start()

    def _read_done(self, devnode, results, message, mode="lighting"):
        self.reading = False
        if results is not None:
            self.feature_results = (devnode, results)
            res = results[0]
            if res.ok:
                prev = self.previous_block
                if prev and prev[0] == devnode and prev[1] == mode:
                    differ = describe_keymap_diff if mode == "keymap" else (
                        lambda a, b: describe_diff(diff_blocks(a, b)))
                    self.last_change = differ(prev[2], res.data)
                else:
                    self.last_change = None
                self.previous_block = (devnode, mode, res.data)
                n = len(self.change_log) + 1
                changes = ("first read" if self.last_change is None
                           else f"changed {self.last_change}" if self.last_change else "no change")
                what = ("key map" if mode == "keymap"
                        else f"bytes 20–21 = {res.data[20]:02x} {res.data[21]:02x}")
                self.change_log.append(f"{n}. {self.pending_note or '(no name)'}: {what}; {changes}")
                self.note_entry.set_text("")
            message = (("Read the key map." if mode == "keymap" else "Read the lighting settings.")
                       if results[0].ok else "The read didn't work.")
        self.feature_message = message
        self.render()
        self.note_entry.grab_focus()
        self.say(message)
        self.scan()
        return False

    def _diagnostics(self) -> str:
        kb = self.current()
        if not kb:
            return ""
        lines = [f"{APP_NAME} {__version__}", f"{kb.label} {kb.vendor_id:04x}:{kb.product_id:04x} "
                 f"bcdDevice {kb.bcd_device} USB {kb.usb_version}"]
        for i in kb.interfaces:
            lines.append(f"interface {i.interface_number}: {i.devnode} descriptor "
                         + " ".join(f"{b:02x}" for b in i.descriptor_bytes))
        if self.feature_results:
            for r in self.feature_results[1]:
                cmd = "05 84 d8" if r.data[:3] == bytes.fromhex("0684d8") else "05 83 c6"
                lines.append(f"Block read (SET_FEATURE {cmd} 00 00 00, then GET_FEATURE 0x06): "
                             f"{len(r.data)} bytes {r.problem}".rstrip())
                lines.append(hexdump(r.data))
        if self.change_log:
            lines.append("Your list:")
            lines += [f"  {line}" for line in self.change_log]
        return "\n".join(lines) + "\n"

    def _copy(self, text, button):
        self.get_clipboard().set(text)
        self.say("Copied")
        old = button.get_label()
        button.set_label("Copied")
        GLib.timeout_add(1500, lambda: (button.set_label(old), False)[1])

    def say(self, text):
        """Announce feedback to screen readers (GTK 4.14+)."""
        # GTK 4.14 crashes in announce() when there is no session/accessibility bus.
        if not text or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            return
        try:
            Gtk.Accessible.announce(self, text, Gtk.AccessibleAnnouncementPriority.MEDIUM)
        except (AttributeError, TypeError):
            pass  # GTK older than 4.14

    # --- settings page -------------------------------------------------------

    # --- keys tab ------------------------------------------------------------------

    def render_keys(self, iface):
        page = self.keys_page
        clear(page)
        if self.keys_state and (iface is None or self.keys_state[0] != iface.devnode):
            self.keys_state = None
        page.append(section("Keys", "Remaps keys on the keyboard itself, so it works on any computer. "
                                    "Changes are saved straight away. Close Redragon's software first."))
        card = vbox(14, "card")
        page.append(card)
        if iface is None or not iface.access:
            card.append(label("Connect the keyboard (and allow access on the Keyboard tab) to remap keys.", "dim"))
            return
        if self.keys_state is None:
            card.append(label("Read the current key layout from the keyboard.", "small", "dim"))
            load = Gtk.Button(label="Reading…" if self.keys_busy else "Load keys")
            load.add_css_class("filled")
            load.set_halign(Gtk.Align.START)
            load.set_sensitive(not self.keys_busy)
            load.connect("clicked", lambda *_: self._keys_run(
                lambda: keymap.read(iface.devnode, handle=self.handle), lambda cur: ""))
            card.append(load)
        else:
            card.append(self._keyboard_view())
            card.append(Gtk.Box(css_classes=["divider"]))
            card.append(self._key_picker(iface))

        text, kind = self.keys_message
        if text:
            card.append(label(text, "small", kind))

        if self.keys_state is not None:
            page.append(section("Reset all keys", None))
            rc = vbox(10, "card")
            rc.append(label("Makes every key type what's printed on it again. Works with the mouse alone, so "
                            "you can always undo a remap that gets in the way.", "small", "dim"))
            btn = Gtk.Button(label="Reset all keys")
            btn.set_halign(Gtk.Align.START)
            btn.set_sensitive(not self.keys_busy)
            btn.connect("clicked", lambda *_: ([self._unassign_macro(k.name) for k in keymap.REMAPPABLE],
                                               self._keys_run(
                lambda: keymap.reset_all(iface.devnode, handle=self.handle),
                lambda now: "All keys are back to default.")))
            rc.append(btn)
            page.append(rc)

    def _keyboard_view(self) -> Gtk.Widget:
        cur = self.keys_state[1]
        by_number = {k.number: k for k in keymap.KEYS}
        buttons = []
        for number, rect in keymap.LAYOUT.items():
            k = by_number.get(number)
            name = k.name if k else keymap.SPECIAL[number]
            cap = keymap.CAP_LABELS.get(name, name) if k else name
            btn = Gtk.Button()
            btn.add_css_class("keycap")
            inner = vbox(0)
            inner.set_valign(Gtk.Align.CENTER)
            inner.append(label(cap, xalign=0.5, wrap=False))
            remapped = k is not None and k.remappable and cur[k.name] != k.default
            if remapped:
                target = "Macro" if cur[k.name] >= keymap.MACRO_CODE else self._code_name(cur[k.name])
                inner.append(label("→ " + keymap.SHORT_TARGETS.get(target, target), "keycap-sub",
                                   xalign=0.5, wrap=False))
                btn.add_css_class("remapped")
            btn.set_child(inner)
            if k is None or not k.remappable:
                btn.set_sensitive(False)
                btn.set_tooltip_text(f"{name} can't be remapped yet")
            else:
                tip = f"{name}: sends {self._code_name(cur[name])}"
                btn.set_tooltip_text(tip)
                set_accessible_label(btn, tip)
                if name == self.keys_selected:
                    btn.add_css_class("selected")
                btn.set_sensitive(not self.keys_busy)
                btn.connect("clicked", lambda *_, n=name: self._select_key(n))
            buttons.append((btn, rect))
        if (parent := self.keyboard_view.get_parent()) is not None:
            parent.remove(self.keyboard_view)
        self.keyboard_view.set_keys(buttons)
        return self.keyboard_view

    def _code_name(self, code):
        if code >= keymap.MACRO_CODE:
            slot = code - keymap.MACRO_CODE
            assigned = [m for m in self.macro_list if m.key]
            return f"macro “{assigned[slot].name}”" if slot < len(assigned) else "a macro"
        return keymap.TARGETS.get(code, f"code 0x{code:02x}")

    def _unassign_macro(self, key_name):
        """Keep macros.json in sync when the Keys tab overwrites a key that plays a macro."""
        changed = False
        for m in self.macro_list:
            if m.key == key_name:
                m.key = None
                changed = True
        if changed:
            macros.save(self.macro_list)

    def _assign_macro_to_key(self, iface, index, key_name):
        m = self.macro_list[index]
        if m.key == key_name:
            return
        old = [(x, x.key) for x in self.macro_list]
        for x in self.macro_list:
            if x.key == key_name:
                x.key = None
        m.key = key_name
        if len([x for x in self.macro_list if x.key]) > macros.SLOTS:
            for x, k in old:
                x.key = k
            self.keys_message = (f"The keyboard holds up to {macros.SLOTS} assigned macros.", "error-text")
            self.render()
            return
        macros.save(self.macro_list)
        self._keys_run(lambda: macros.apply(iface.devnode, self.macro_list, handle=self.handle),
                       lambda now: f"{key_name} plays “{m.name}” now.")

    def _select_key(self, name):
        self.keys_selected = name
        self.keys_message = ("", "dim")
        GLib.idle_add(lambda: (self.render(), False)[1])

    def _key_picker(self, iface) -> Gtk.Widget:
        cur = self.keys_state[1]
        key = next(k for k in keymap.REMAPPABLE if k.name == self.keys_selected)
        codes = list(keymap.TARGETS)
        box = vbox(10)
        box.append(label(key.name, "heading"))
        row = hbox(10)
        row.append(label("Sends", "dim", wrap=False))
        playing = [i for i, m in enumerate(self.macro_list) if m.key == key.name]
        current_macro = playing[0] if cur[key.name] >= keymap.MACRO_CODE and playing else None
        shown = (f"Macro “{self.macro_list[current_macro].name}”" if current_macro is not None
                 else self._code_name(cur[key.name]))
        choose = Gtk.Button(label=f"{shown}  ▾")
        choose.set_tooltip_text("Choose what this key sends")
        set_accessible_label(choose, f"{key.name} sends {shown}. Choose another key")
        choose.set_sensitive(not self.keys_busy)

        def picked(kind, value):
            if kind == "macro":
                self._assign_macro_to_key(iface, value, key.name)
                return
            if cur.get(key.name) == value:
                return
            self._unassign_macro(key.name)
            self._keys_run(lambda: keymap.remap(iface.devnode, {key.name: value}, handle=self.handle),
                           lambda now: f"{key.name} now sends {keymap.TARGETS[value]}.")
        choose.connect("clicked", lambda *_: KeyChooser(
            self, f"What should {key.name} send?", cur[key.name], picked,
            [m.name for m in self.macro_list], current_macro).present())
        row.append(choose)
        if cur[key.name] != key.default:
            undo = Gtk.Button(label=f"Reset {key.name}")
            undo.add_css_class("text")
            undo.connect("clicked", lambda *_: (self._unassign_macro(key.name), self._keys_run(
                lambda: keymap.remap(iface.devnode, {key.name: key.default}, handle=self.handle),
                lambda now: f"Reset {key.name}.")))
            row.append(undo)
        box.append(row)
        box.append(label("Click a key to change it. Fn is locked, because it switches the keyboard's "
                         "Fn layer. The macro, media and volume controls aren't part "
                         "of the key map.", "small", "dim"))

        box.append(Gtk.Box(css_classes=["divider"]))
        changed = [k for k in keymap.REMAPPABLE if cur[k.name] != k.default]
        box.append(label(f"Remapped keys ({len(changed)})" if changed else "Remapped keys", "heading"))
        if not changed:
            box.append(label("None. Remapped keys are tinted on the keyboard above and listed here.",
                             "small", "dim"))
        for k in changed:
            r = hbox(10)
            sends = self._code_name(cur[k.name])
            name_btn = Gtk.Button(label=f"{k.name}  →  {sends}")
            name_btn.add_css_class("text")
            name_btn.set_hexpand(True)
            name_btn.set_halign(Gtk.Align.START)
            name_btn.set_tooltip_text(f"Select {k.name} on the keyboard")
            name_btn.connect("clicked", lambda *_, n=k.name: self._select_key(n))
            r.append(name_btn)
            undo = Gtk.Button(label="Reset")
            undo.add_css_class("text")
            set_accessible_label(undo, f"Reset {k.name}")
            undo.set_sensitive(not self.keys_busy)
            undo.connect("clicked", lambda *_, key=k: (self._unassign_macro(key.name), self._keys_run(
                lambda: keymap.remap(iface.devnode, {key.name: key.default}, handle=self.handle),
                lambda now, key=key: f"Reset {key.name}.")))
            r.append(undo)
            box.append(r)
        return box

    def _keys_run(self, job, describe):
        kb = self.current()
        iface = kb.config_interface if kb else None
        if iface is None or self.keys_busy:
            return
        self.keys_busy = True
        self.keys_message = ("", "dim")
        GLib.idle_add(lambda: (self.render(), False)[1])
        devnode = iface.devnode

        def work():
            try:
                cur = job()
                result = (cur, (describe(cur), "dim"))
            except keymap.VerifyFailed:
                result = (None, ("The keyboard didn't keep the change. Load the keys again to see what it "
                                 "has now.", "error-text"))
            except keymap.UnexpectedKeymap as e:
                result = (None, (f"The key map doesn't look as expected, so nothing was changed. {e}",
                                 "error-text"))
            except ValueError as e:
                result = (None, (str(e), "error-text"))
            except AccessDenied:
                result = (None, ("Access denied. The Keyboard tab shows how to allow it.", "error-text"))
            except DeviceGone:
                result = (None, ("The keyboard was disconnected.", "error-text"))
            except (WriteFailed, OSError) as e:
                result = (None, (f"Couldn't talk to the keyboard: {e}. Load the keys again to check them.",
                                 "error-text"))
            GLib.idle_add(self._keys_done, devnode, result)
        threading.Thread(target=work, daemon=True).start()

    def _keys_done(self, devnode, result):
        self.keys_busy = False
        cur, self.keys_message = result
        self.keys_state = (devnode, cur) if cur else None
        self.render()
        self.say(self.keys_message[0])
        return False

    # --- macros tab ------------------------------------------------------------------

    def render_macros(self, iface):
        page = self.macros_page
        clear(page)
        page.append(section("Macros", "Macros play key presses with pauses when you press a key. They're "
                                      "stored in the keyboard, so they work on any computer. G1–G4 can only "
                                      "be recorded on the keyboard itself (MR)."))
        if self.editing is not None:
            page.append(self._macro_editor(iface))
            return
        card = vbox(12, "card")
        if not self.macro_list:
            card.append(label("No macros yet. Create one, then assign it to a key.", "small", "dim"))
        for i, m in enumerate(self.macro_list):
            if i:
                card.append(Gtk.Box(css_classes=["divider"]))
            row = hbox(10)
            text = vbox(2)
            text.set_hexpand(True)
            text.append(label(m.name, "heading"))
            how = "while held" if m.held else (f"{m.count} times" if m.count > 1 else "once")
            where = f"on {m.key}" if m.key else "not assigned"
            text.append(label(f"{len(m.steps)} steps · plays {how} · {where}", "small", "dim"))
            row.append(text)
            edit = Gtk.Button(label="Edit")
            edit.connect("clicked", lambda *_, i=i: self._edit_macro(i))
            row.append(edit)
            delete = Gtk.Button(label="Delete")
            delete.add_css_class("text")
            set_accessible_label(delete, f"Delete {m.name}")
            delete.connect("clicked", lambda *_, i=i: self._delete_macro(iface, i))
            row.append(delete)
            card.append(row)
        new = Gtk.Button(label="New macro")
        new.add_css_class("filled")
        new.set_halign(Gtk.Align.START)
        new.connect("clicked", lambda *_: self._edit_macro(None))
        card.append(new)
        text, kind = self.keys_message
        if text:
            card.append(label(text, "small", kind))
        card.append(label("The app keeps your macros in ~/.config/k609-keyboard-control/macros.json, because "
                          "the keyboard can't report them back. Applying macros here replaces macros set in "
                          "Redragon's software.", "small", "faint"))
        page.append(card)

    def _edit_macro(self, index):
        import copy
        m = copy.deepcopy(self.macro_list[index]) if index is not None else macros.Macro(
            "New macro", [macros.Step(0x04, True, 30), macros.Step(0x04, False, 30)])
        self.editing = (index, m)
        self.keys_message = ("", "dim")
        GLib.idle_add(lambda: (self.render(), False)[1])

    def _delete_macro(self, iface, index):
        removed = self.macro_list.pop(index)
        macros.save(self.macro_list)
        if removed.key and iface is not None and iface.access:
            self._keys_run(lambda: macros.apply(iface.devnode, self.macro_list, handle=self.handle),
                           lambda now: f"Deleted {removed.name}. {removed.key} types normally again.")
        else:
            self.keys_message = (f"Deleted {removed.name}.", "dim")
            GLib.idle_add(lambda: (self.render(), False)[1])

    def _macro_editor(self, iface) -> Gtk.Widget:
        index, m = self.editing
        codes = list(keymap.TARGETS)
        card = vbox(14, "card")
        name = Gtk.Entry(text=m.name)
        set_accessible_label(name, "Macro name")
        name.connect("changed", lambda e: setattr(m, "name", e.get_text()))
        card.append(label("Name", "heading"))
        card.append(name)

        card.append(label("Steps", "heading"))
        card.append(label("Each step presses or releases a key, then pauses. Pauses up to 127 ms can be any "
                          "value; longer pauses go in steps of 100 ms.", "small", "dim"))
        for i, st in enumerate(m.steps):
            row = hbox(8)
            act = Gtk.DropDown.new_from_strings(["Press", "Release"])
            act.set_selected(0 if st.down else 1)
            set_accessible_label(act, f"Step {i + 1} action")
            act.connect("notify::selected", lambda d, _p, st=st: setattr(st, "down", d.get_selected() == 0))
            row.append(act)
            key = Gtk.Button(label=f"{keymap.TARGETS.get(st.key, '?')}  ▾")
            key.set_tooltip_text("Choose the key")
            set_accessible_label(key, f"Step {i + 1} key: {keymap.TARGETS.get(st.key, '?')}. Choose another key")
            key.connect("clicked", lambda *_, i=i, st=st: KeyChooser(
                self, f"Step {i + 1}: which key?", st.key,
                lambda kind, code, i=i: (self._set_step_key(m, i, code), self.render())).present())
            row.append(key)
            row.append(label("then wait", "dim", wrap=False))
            spin = Gtk.SpinButton.new_with_range(0, macros.LONG_MAX, 10)
            spin.set_value(st.pause)
            set_accessible_label(spin, f"Step {i + 1} pause in milliseconds")
            spin.connect("value-changed", lambda w, st=st: setattr(st, "pause", int(w.get_value())))
            row.append(spin)
            row.append(label("ms", "dim", wrap=False))
            rm = icon_button("list-remove-symbolic", f"Remove step {i + 1}",
                             lambda i=i: (m.steps.pop(i), self.render()))
            row.append(rm)
            card.append(row)
        add = hbox(8)
        tap = Gtk.Button(label="Add key press")
        tap.set_tooltip_text("Adds a press and a release of the same key, 30 ms apart")
        tap.connect("clicked", lambda *_: (m.steps.extend([macros.Step(0x04, True, 30), macros.Step(0x04, False, 30)]),
                                           self.render()))
        add.append(tap)
        one = Gtk.Button(label="Add step")
        one.add_css_class("text")
        one.connect("clicked", lambda *_: (m.steps.append(macros.Step(0x04, True, 30)), self.render()))
        add.append(one)
        card.append(add)

        card.append(Gtk.Box(css_classes=["divider"]))
        card.append(self._group_row("Repeat", "Play it a number of times, or keep repeating while the key is held.",
                                    [("times", "Number of times"), ("held", "While held")],
                                    "held" if m.held else "times",
                                    lambda v: (setattr(m, "held", v == "held"),
                                               GLib.idle_add(lambda: (self.render(), False)[1]))))
        if not m.held:
            row = hbox(8)
            row.append(label("Times", "dim", wrap=False))
            count = Gtk.SpinButton.new_with_range(1, 255, 1)
            count.set_value(m.count)
            set_accessible_label(count, "Number of times")
            count.connect("value-changed", lambda w: setattr(m, "count", int(w.get_value())))
            row.append(count)
            card.append(row)

        card.append(Gtk.Box(css_classes=["divider"]))
        card.append(label("Key", "heading"))
        names = ["Not assigned"] + [k.name for k in keymap.REMAPPABLE]
        key_dd = Gtk.DropDown.new_from_strings(names)
        key_dd.set_selected(names.index(m.key) if m.key in names else 0)
        key_dd.set_halign(Gtk.Align.START)
        set_accessible_label(key_dd, "Key that plays the macro")
        key_dd.connect("notify::selected", lambda d, _p: setattr(m, "key", None if d.get_selected() == 0
                                                                   else names[d.get_selected()]))
        card.append(key_dd)
        card.append(label("The key stops typing its own character while the macro is on it.", "small", "dim"))

        text, kind = self.keys_message
        if text:
            card.append(label(text, "small", kind))
        btns = hbox(8)
        save = Gtk.Button(label="Save and apply" if iface is not None and iface.access else "Save")
        save.add_css_class("filled")
        save.set_sensitive(not self.keys_busy)
        save.connect("clicked", lambda *_: self._save_macro(iface))
        btns.append(save)
        cancel = Gtk.Button(label="Cancel")
        cancel.add_css_class("text")
        cancel.connect("clicked", lambda *_: (setattr(self, "editing", None), self.render()))
        btns.append(cancel)
        card.append(btns)
        return card

    def _set_step_key(self, m, i, code):
        """Change a step's key; for a press, also change the release of the same key that follows it."""
        st = m.steps[i]
        old = st.key
        st.key = code
        if st.down and old != code:
            for later in m.steps[i + 1:]:
                if later.key == old and later.down:
                    break
                if later.key == old and not later.down:
                    later.key = code
                    GLib.idle_add(lambda: (self.render(), False)[1])
                    break

    def _save_macro(self, iface):
        index, m = self.editing
        try:
            macros.validate(m)
            if m.key and any(o.key == m.key for j, o in enumerate(self.macro_list) if j != index):
                raise ValueError(f"Another macro is already on {m.key}.")
            new_list = list(self.macro_list)
            if index is None:
                new_list.append(m)
            else:
                new_list[index] = m
            if len([x for x in new_list if x.key]) > macros.SLOTS:
                raise ValueError(f"The keyboard holds up to {macros.SLOTS} assigned macros.")
        except ValueError as e:
            self.keys_message = (str(e), "error-text")
            self.render()
            return
        self.macro_list = new_list
        macros.save(self.macro_list)
        self.editing = None
        if iface is not None and iface.access:
            self._keys_run(lambda: macros.apply(iface.devnode, self.macro_list, handle=self.handle),
                           lambda now: f"Saved {m.name}" + (f". {m.key} plays it now." if m.key else "."))
        else:
            self.keys_message = (f"Saved {m.name}. Connect the keyboard to apply it.", "dim")
            self.render()

    # --- profiles tab ----------------------------------------------------------------

    def _iface(self):
        kb = self.current()
        return kb.config_interface if kb else None

    def render_profiles(self, iface):
        page = self.profiles_page
        clear(page)
        page.append(section("Profiles", "A profile holds the lighting, key remaps and macros. Applying one "
                                        "writes them all to the keyboard. The keyboard has no profiles of its "
                                        "own, so they're stored by this app."))
        ready = iface is not None and iface.access
        card = vbox(10, "card")
        card.append(label("Save the current settings", "heading"))
        row = hbox(10)
        if (parent := self.profile_name.get_parent()) is not None:
            parent.remove(self.profile_name)
        row.append(self.profile_name)
        save = Gtk.Button(label="Saving…" if self.profile_busy else "Save profile")
        save.add_css_class("filled")
        save.set_sensitive(ready and not self.profile_busy)
        save.connect("clicked", lambda *_: self._save_profile(iface))
        row.append(save)
        card.append(row)
        if not ready:
            card.append(label("Connect the keyboard to save or apply profiles.", "small", "dim"))
        text, kind = self.profile_message
        if text:
            card.append(label(text, "small", kind))
        page.append(card)

        saved = profiles.load_all()
        page.append(section("Saved profiles", None))
        lst = vbox(12, "card")
        imp = Gtk.Button(label="Import…")
        imp.set_halign(Gtk.Align.START)
        imp.set_tooltip_text("Adds a profile from a file exported by this app")
        imp.connect("clicked", lambda *_: self._import_profile())
        lst.append(imp)
        if not saved:
            lst.append(label("No profiles yet.", "small", "dim"))
        for i, p in enumerate(saved):
            if i:
                lst.append(Gtk.Box(css_classes=["divider"]))
            row = hbox(10)
            text = vbox(2)
            text.set_hexpand(True)
            text.append(label(p.name, "heading"))
            remapped = sum(1 for k in keymap.REMAPPABLE if p.keys.get(k.name, k.default) != k.default)
            assigned = sum(1 for m in p.macros if m.key)
            colour = f" · colour #{p.colour}" if p.colour and p.effect == 0x01 else ""
            text.append(label(f"{lighting.EFFECTS[p.effect]}{colour} · {remapped} remapped "
                              f"key{'s' if remapped != 1 else ''} · {assigned} macro{'s' if assigned != 1 else ''}",
                              "small", "dim"))
            row.append(text)
            apply_btn = Gtk.Button(label="Apply")
            apply_btn.add_css_class("filled")
            apply_btn.set_sensitive(ready and not self.profile_busy)
            apply_btn.connect("clicked", lambda *_, p=p: self._apply_profile(iface, p))
            row.append(apply_btn)
            exp = Gtk.Button(label="Export…")
            exp.add_css_class("text")
            exp.set_tooltip_text("Saves this profile to a file you choose")
            exp.connect("clicked", lambda *_, p=p: self._export_profile(p))
            row.append(exp)
            bind = Gtk.Button(label="Copy binding")
            bind.add_css_class("text")
            bind.set_tooltip_text("Copies a Hyprland line that applies this profile from a key")
            bind.connect("clicked", lambda *_, p=p, b=bind: self._copy(self._binding(p), b))
            row.append(bind)
            delete = Gtk.Button(label="Delete")
            delete.add_css_class("text")
            set_accessible_label(delete, f"Delete profile {p.name}")
            delete.connect("clicked", lambda *_, p=p: self._delete_profile(p))
            row.append(delete)
            lst.append(row)
        if saved:
            lst.append(label("To switch profiles from the keyboard: remap a spare key to F13–F24 on the Keys tab, "
                             "copy a binding, paste it into your Hyprland config and change F13 to that key.",
                             "small", "faint"))
        page.append(lst)

    @staticmethod
    def _binding(p) -> str:
        """A Hyprland line for this profile (F13 as a placeholder key)."""
        exe = os.environ.get("APPIMAGE") or "k609-keyboard-control"
        return f'bind = , F13, exec, "{exe}" --apply-profile "{p.name}"\n'

    def _save_profile(self, iface):
        name = self.profile_name.get_text().strip()
        if not name:
            self.profile_message = ("Type a name for the profile first.", "error-text")
            self.render()
            return
        existing = profiles.find(name)
        colour = self.app.settings.fixed_colour or None
        current = list(self.macro_list)
        selfdef, sb = dict(self.selfdef), self.selfdef_brightness
        self._profile_run(iface, lambda dev: profiles.save(profiles.capture(dev, name, colour, current, selfdef, sb,
                                                                            handle=self.handle)),
                          lambda _r: f"{'Updated' if existing else 'Saved'} profile “{name}”.",
                          clear_name=True)

    def _apply_profile(self, iface, p):
        def job(dev):
            profiles.apply(dev, p, handle=self.handle)
            return p
        self._profile_run(iface, job, lambda _r: f"Applied profile “{p.name}”.", applied=True)

    @staticmethod
    def _json_filter() -> Gio.ListStore:
        f = Gtk.FileFilter()
        f.set_name("Profiles (JSON)")
        f.add_pattern("*.json")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        return store

    def _choose_file(self, title, save, initial_name, on_path):
        """A file dialog: Gtk.FileDialog on GTK 4.10+, Gtk.FileChooserNative on older GTK."""
        if hasattr(Gtk, "FileDialog"):
            dlg = Gtk.FileDialog(title=title, filters=self._json_filter())
            if initial_name:
                dlg.set_initial_name(initial_name)

            def done(d, res):
                try:
                    f = d.save_finish(res) if save else d.open_finish(res)
                except GLib.Error:
                    return                      # cancelled
                on_path(f.get_path())
            (dlg.save if save else dlg.open)(self, None, done)
            return
        action = Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN
        native = Gtk.FileChooserNative.new(title, self, action, None, None)
        f = Gtk.FileFilter()
        f.set_name("Profiles (JSON)")
        f.add_pattern("*.json")
        native.add_filter(f)
        if initial_name and save:
            native.set_current_name(initial_name)

        def response(n, r):
            if r == Gtk.ResponseType.ACCEPT and n.get_file() is not None:
                on_path(n.get_file().get_path())
            self._native = None
        native.connect("response", response)
        self._native = native                   # keep a reference while it's open
        native.show()

    def _export_profile(self, p):
        def write(path):
            try:
                profiles.export_to(p, path)
                self.profile_message = (f"Exported “{p.name}” to {path}.", "dim")
            except (OSError, ValueError) as e:
                self.profile_message = (f"Couldn't export it: {e}", "error-text")
            self.render()
        self._choose_file(f"Export profile “{p.name}”", True, profiles.file_name(p.name), write)

    def _import_profile(self):
        def read(path):
            try:
                p = profiles.import_from(path)
                self.profile_message = (f"Imported profile “{p.name}”. Apply it to write it to the keyboard.", "dim")
            except (OSError, ValueError) as e:
                self.profile_message = (f"Couldn't import that file: {e}", "error-text")
            self.render()
        self._choose_file("Import a profile", False, None, read)

    def _delete_profile(self, p):
        try:
            profiles.delete(p.name)
            self.profile_message = (f"Deleted profile “{p.name}”.", "dim")
        except OSError as e:
            self.profile_message = (f"Couldn't delete it: {e.strerror}.", "error-text")
        self.render()

    def _profile_run(self, iface, job, describe, clear_name=False, applied=False):
        if iface is None or not iface.access or self.profile_busy:
            return
        self.profile_busy = True
        self.profile_message = ("", "dim")
        self.render()
        devnode = iface.devnode

        def work():
            try:
                r = job(devnode)
                result = (True, r, (describe(r), "dim"))
            except AccessDenied:
                result = (False, None, ("Access denied. The Keyboard tab shows how to allow it.", "error-text"))
            except DeviceGone:
                result = (False, None, ("The keyboard was disconnected.", "error-text"))
            except (ValueError, RuntimeError, OSError) as e:
                result = (False, None, (f"That didn't work: {e}", "error-text"))
            GLib.idle_add(done, result)

        def done(result):
            ok, r, self.profile_message = result
            self.profile_busy = False
            if ok and clear_name:
                self.profile_name.set_text("")
            if ok and applied:
                import copy
                self.macro_list = copy.deepcopy(r.macros)
                macros.save(self.macro_list)
                if r.colour:
                    self.app.change(fixed_colour=r.colour)
                    self.picker_rgb = None
                if r.selfdef:
                    self.selfdef = dict(r.selfdef)
                    self.selfdef_brightness = r.selfdef_brightness
                    selfdefine.save(self.selfdef, brightness=self.selfdef_brightness)
                self.keys_state = None          # reload from the keyboard next time
                self.light_state = None
                self.autoloaded.clear()
            self.render()
            self.say(self.profile_message[0])
            return False
        threading.Thread(target=work, daemon=True).start()

    # --- lighting tab ------------------------------------------------------------

    def render_lighting(self, iface):
        page = self.lighting_page
        clear(page)
        if self.light_state and (iface is None or self.light_state[0] != iface.devnode):
            self.light_state = None
        page.append(section("Lighting", "Changes are saved on the keyboard straight away. Close "
                                        "Redragon's software first, so the two don't use the keyboard "
                                        "at the same time."))
        card = vbox(16, "card")
        page.append(card)
        if iface is None:
            card.append(label("Connect the keyboard with its USB cable to change its lighting.", "dim"))
            return
        if not iface.access:
            card.append(label("The app can't open the keyboard yet. The Keyboard tab shows how to "
                              "allow it.", "dim"))
            return

        if self.light_state is None:
            card.append(label("Read the current effect, brightness and speed from the keyboard.", "small", "dim"))
            load = Gtk.Button(label="Reading…" if self.light_busy else "Load current lighting")
            load.add_css_class("filled")
            load.set_halign(Gtk.Align.START)
            load.set_sensitive(not self.light_busy)
            load.connect("clicked", lambda *_: self._light_run(
                lambda: lighting.read_state(iface.devnode, handle=self.handle), lambda st: ""))
            card.append(load)
        else:
            st = self.light_state[1]
            codes = list(lighting.EFFECTS)
            effect_box = vbox(8)
            effect_box.append(label("Effect", "heading"))
            dd = Gtk.DropDown.new_from_strings([lighting.EFFECTS[c] for c in codes])
            dd.set_selected(codes.index(st.effect))
            dd.set_halign(Gtk.Align.START)
            dd.set_sensitive(not self.light_busy)
            set_accessible_label(dd, "Lighting effect")
            dd.connect("notify::selected", lambda d, _p: self._set_light(
                iface, f"Set {lighting.EFFECTS[codes[d.get_selected()]]}.", effect=codes[d.get_selected()]))
            effect_box.append(dd)
            card.append(effect_box)
            if st.effect == lighting.SELF_DEFINE:
                card.append(Gtk.Box(css_classes=["divider"]))
                card.append(self._selfdefine_section(iface))
            if st.effect == 0x01:
                card.append(Gtk.Box(css_classes=["divider"]))
                card.append(self._colour_section(iface))

            levels = [(str(i), str(i)) for i in range(lighting.MAX_LEVEL + 1)]
            if st.brightness is not None:
                for title, expl, key, cur in (
                        ("Brightness", f"For {st.name}. 0 turns the lights off, 4 is brightest.",
                         "brightness", st.brightness),
                        ("Speed", f"For {st.name}. 0 is slowest, 4 is fastest. Some effects don't move.",
                         "speed", st.speed)):
                    card.append(Gtk.Box(css_classes=["divider"]))
                    row = self._group_row(title, expl, levels, str(cur),
                                          lambda v, k=key, t=title: self._set_light(
                                              iface, f"{t} {v} for {st.name}.", **{k: int(v)}))
                    row.set_sensitive(not self.light_busy)
                    card.append(row)
            else:
                if st.effect != lighting.SELF_DEFINE:
                    card.append(label(f"{st.name} has no brightness or speed setting.", "small", "dim"))

        text, kind = self.light_message
        if text:
            card.append(label(text, "small", kind))

        saved = lighting.load_backup(lighting.backup_path())
        page.append(section("Restore", None))
        rc = vbox(10, "card")
        if saved:
            rc.append(label("Puts back the effect, brightness and speed the keyboard had before your first "
                            f"change in this app (saved {saved[0].replace('T', ' at ')}).", "small", "dim"))
            btn = Gtk.Button(label="Restore")
            btn.set_halign(Gtk.Align.START)
            btn.set_sensitive(not self.light_busy)
            btn.connect("clicked", lambda *_: self._light_run(
                lambda: lighting.restore(iface.devnode, lighting.backup_path(), self._known_colour(),
                                        handle=self.handle),
                lambda st: f"Restored {st.name}."))
            rc.append(btn)
        else:
            rc.append(label("Before your first change, the app saves the keyboard's effect, brightness "
                            "and speed so you can put them back here.", "small", "dim"))
        page.append(rc)

    def _selfdefine_section(self, iface) -> Gtk.Widget:
        box = vbox(10)
        box.append(label("Key colours", "heading"))
        box.append(label("Click keys to paint them with the colour below, then send. The keyboard can't report "
                         "its key colours, so this shows what was last sent from this app.", "small", "dim"))
        by_number = {k.number: k for k in keymap.KEYS}
        buttons = []
        for number, rect in keymap.LAYOUT.items():
            k = by_number.get(number)
            name = k.name if k else keymap.SPECIAL[number]
            rgb = self.selfdef.get(number, (0, 0, 0))
            btn = Gtk.Button()
            btn.add_css_class("keycap")
            btn.add_css_class("paint")
            fill = KeyColour(rgb)
            overlay = Gtk.Overlay()
            overlay.set_child(fill)
            cap = label(keymap.CAP_LABELS.get(name, name) if k else name, f"text-on-{readable_on(rgb)}",
                        xalign=0.5, wrap=False)
            cap.set_halign(Gtk.Align.CENTER)
            cap.set_valign(Gtk.Align.CENTER)
            overlay.add_overlay(cap)
            btn.set_child(overlay)
            set_accessible_label(btn, f"Paint {name}")
            btn.set_tooltip_text(f"{name}: #{bytes(rgb).hex()}")
            btn.connect("clicked", lambda b, n=number, f=fill, c=cap, nm=name: self._paint_key(n, f, c, b, nm))
            buttons.append((btn, rect))
        if (parent := self.selfdef_view.get_parent()) is not None:
            parent.remove(self.selfdef_view)
        self.selfdef_view.set_keys(buttons)
        box.append(self.selfdef_view)
        levels = [(str(i), str(i)) for i in range(selfdefine.MAX_BRIGHTNESS + 1)]
        bright = self._group_row("Brightness", "Dims every key's colour when sending: 4 is as painted, 0 turns "
                                               "the keys off. Changes are sent straight away.",
                                 levels, str(self.selfdef_brightness),
                                 lambda v: self._set_selfdef_brightness(iface, int(v)))
        bright.set_sensitive(not self.light_busy)
        box.append(bright)
        box.append(label("Paint colour", "heading"))
        box.append(ColourPicker(self.paint_rgb, lambda rgb: self._paint_all(rgb), apply_label="Paint all keys",
                                on_change=lambda rgb: setattr(self, "paint_rgb", rgb)))
        row = hbox(10)
        send = Gtk.Button(label="Send to keyboard")
        send.add_css_class("filled")
        send.set_sensitive(not self.light_busy)
        send.connect("clicked", lambda *_: self._send_selfdef(iface))
        row.append(send)
        clear_btn = Gtk.Button(label="Clear all")
        clear_btn.add_css_class("text")
        clear_btn.set_tooltip_text("Sets every key to black in the editor; Send to keyboard to apply")
        clear_btn.connect("clicked", lambda *_: self._paint_all((0, 0, 0)))
        row.append(clear_btn)
        if self.selfdef_dirty:
            hint = label("Not sent yet.", "small", "dim")
            hint.set_valign(Gtk.Align.CENTER)
            row.append(hint)
        box.append(row)
        return box

    def _paint_key(self, number, fill, cap, button, name):
        rgb = tuple(self.paint_rgb)
        self.selfdef[number] = rgb
        fill.set_rgb(rgb)
        for side in ("dark", "light"):
            cap.remove_css_class(f"text-on-{side}")
        cap.add_css_class(f"text-on-{readable_on(rgb)}")
        button.set_tooltip_text(f"{name}: #{bytes(rgb).hex()}")
        if not self.selfdef_dirty:
            self.selfdef_dirty = True
            GLib.idle_add(lambda: (self.render(), False)[1])

    def _paint_all(self, rgb):
        self.selfdef = {n: tuple(rgb) for n in keymap.LAYOUT}
        self.selfdef_dirty = True
        self.render()

    def _set_selfdef_brightness(self, iface, level):
        if level == self.selfdef_brightness:
            return
        self.selfdef_brightness = level
        self._send_selfdef(iface, f"Brightness {level} for Self define.")

    def _send_selfdef(self, iface, message="Sent the key colours."):
        colours = dict(self.selfdef)
        level = self.selfdef_brightness

        def job():
            st = selfdefine.apply(iface.devnode, colours, level, handle=self.handle)
            selfdefine.save(colours, brightness=level)
            self.selfdef_dirty = False
            return st
        self._light_run(job, lambda st: message)

    def _colour_section(self, iface) -> Gtk.Widget:
        from .style import SWATCHES
        box = vbox(10)
        box.append(label("Colour", "heading"))
        last = self.app.settings.fixed_colour
        box.append(label("The keyboard can't report its colour, so check the keys after you pick one. "
                         + (f"Last sent from here: #{last}." if last else ""), "small", "dim"))
        swatches = hbox(10)
        for name, hexv in SWATCHES:
            b = Gtk.Button(tooltip_text=name, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            b.add_css_class("swatch")
            b.add_css_class(f"swatch-{hexv}")
            if hexv == last:
                b.add_css_class("current")
            set_accessible_label(b, f"Set Fixed on colour to {name.lower()}")
            b.set_sensitive(not self.light_busy)
            b.connect("clicked", lambda *_, h=hexv, n=name: (setattr(self, "picker_rgb", tuple(bytes.fromhex(h))),
                                                             self._send_colour(iface, h, n.lower())))
            swatches.append(b)
        box.append(swatches)
        if self.picker_rgb is None:
            self.picker_rgb = tuple(bytes.fromhex(last)) if last else (255, 255, 255)
        picker = ColourPicker(self.picker_rgb,
                              lambda rgb: self._send_colour(iface, bytes(rgb).hex(), "#" + bytes(rgb).hex()),
                              on_change=lambda rgb: setattr(self, "picker_rgb", rgb))
        picker.set_sensitive_apply(not self.light_busy)
        box.append(picker)
        box.append(label("Dragging only changes the preview; Apply colour sends it to the keyboard.",
                         "small", "faint"))
        return box

    def _send_colour(self, iface, hexv, name):
        if self.light_busy:
            return
        rgb = tuple(bytes.fromhex(hexv))

        def job():
            st = lighting.set_fixed_colour(iface.devnode, rgb, handle=self.handle)
            GLib.idle_add(lambda: (self.app.change(fixed_colour=hexv), False)[1])
            return st
        self._light_run(job, lambda st: f"Sent {name}. Check the keyboard: the colour can't be read back.")

    def _set_light(self, iface, message, **change):
        if self.light_busy:
            return
        cur = self.light_state[1] if self.light_state else None
        if cur and all(getattr(cur, k) == v for k, v in change.items()):
            return
        colour = self._known_colour()
        self._light_run(lambda: lighting.apply(iface.devnode, backup=lighting.backup_path(), handle=self.handle,
                                               colour=colour, **change),
                        lambda st: message)

    def _known_colour(self):
        """The Fixed on colour last sent from here, so saves can include it as the official
        software does. None if Keyboard Control has never set one: the table isn't sent then."""
        fc = self.app.settings.fixed_colour
        return tuple(bytes.fromhex(fc)) if fc else None

    def _light_run(self, job, describe):
        kb = self.current()
        iface = kb.config_interface if kb else None
        if iface is None or self.light_busy:
            return
        self.light_busy = True
        self.light_message = ("", "dim")
        GLib.idle_add(lambda: (self.render(), False)[1])
        devnode = iface.devnode

        def work():
            try:
                st = job()
                result = (st, (describe(st), "dim"))
            except lighting.VerifyFailed:
                result = (None, ("The keyboard didn't keep the change. Load the lighting again to see "
                                 "what it has now.", "error-text"))
            except lighting.UnexpectedBlock as e:
                result = (None, (f"The keyboard's settings don't look as expected, so nothing was changed. {e}",
                                 "error-text"))
            except AccessDenied:
                result = (None, ("Access denied. The Keyboard tab shows how to allow it.", "error-text"))
            except DeviceGone:
                result = (None, ("The keyboard was disconnected.", "error-text"))
            except FileNotFoundError:
                result = (None, ("There's no saved lighting to restore.", "error-text"))
            except (WriteFailed, OSError) as e:
                result = (None, (f"Couldn't talk to the keyboard: {e}. Load the lighting again to check it.",
                                 "error-text"))
            GLib.idle_add(self._light_done, devnode, result)
        threading.Thread(target=work, daemon=True).start()

    def _light_done(self, devnode, result):
        self.light_busy = False
        st, self.light_message = result
        self.light_state = (devnode, st) if st else None
        self.render()
        self.say(self.light_message[0])
        return False

    def _build_settings(self):
        s = self.app.settings
        page = self.settings_page
        clear(page)

        page.append(section("Appearance", "Changes apply straight away."))
        card = vbox(16, "card")
        card.append(self._group_row("Theme", "System follows your desktop's light or dark preference.",
                                    [("system", "System"), ("light", "Light"), ("dark", "Dark")],
                                    s.theme, lambda v: self.app.change(theme=v)))
        card.append(Gtk.Box(css_classes=["divider"]))
        card.append(self._group_row("Size", "Makes text and controls smaller or larger.",
                                    [("compact", "Compact"), ("default", "Default"), ("large", "Large")],
                                    s.size, lambda v: self.app.change(size=v)))
        card.append(Gtk.Box(css_classes=["divider"]))

        row = hbox(12)
        text = vbox(4)
        text.set_hexpand(True)
        text.append(label("Reduce motion", "heading"))
        text.append(label("Turns off animations. Your desktop's setting is also respected.", "small", "dim"))
        row.append(text)
        sw = Gtk.Switch(active=s.reduce_motion, valign=Gtk.Align.CENTER)
        set_accessible_label(sw, "Reduce motion")
        sw.connect("notify::active", lambda w, _p: self.app.change(reduce_motion=w.get_active()))
        row.append(sw)
        card.append(row)
        card.append(Gtk.Box(css_classes=["divider"]))
        card.append(self._accent_row())
        page.append(card)

        page.append(section("App launcher", None))
        lc = vbox(10, "card")
        row = hbox(12)
        text = vbox(4)
        text.set_hexpand(True)
        text.append(label("Show in the app launcher", "heading"))
        running = desktop.appimage_path()
        text.append(label(f"Adds “{desktop.LAUNCHER_NAME}” to your launcher, pointing at this AppImage. It follows "
                          "the AppImage if you move or rebuild it. Turning it off removes the entry."
                          if running else "Available when you run the AppImage.", "small", "dim"))
        row.append(text)
        lsw = Gtk.Switch(active=s.desktop_entry, valign=Gtk.Align.CENTER, sensitive=bool(running))
        set_accessible_label(lsw, "Show in the app launcher")
        lsw.connect("notify::active", lambda w, _p: (self.app.change(desktop_entry=w.get_active()),
                                                     self.app.sync_launcher()))
        row.append(lsw)
        lc.append(row)
        page.append(lc)

        page.append(section("About", None))
        about = vbox(6, "card")
        about.append(label(f"{APP_NAME} {__version__}", "heading"))
        about.append(label("Lighting, key remapping, macros and profiles for keyboards compatible with the "
                           "Redragon Horus SE K609, over wired USB. Unofficial: not affiliated with or endorsed by "
                           "Redragon. Written almost entirely by an AI assistant, directed and tested by HypestHyper. "
                           "Settings are saved in ~/.config/k609-keyboard-control/.", "small", "dim"))
        page.append(about)

    def _accent_row(self) -> Gtk.Widget:
        from .style import ACCENTS
        s = self.app.settings
        box = vbox(8)
        box.append(label("Accent colour", "heading"))
        box.append(label("Colours the whole app. Pick one, or make your own.", "small", "dim"))
        row = hbox(10)
        presets = {h for _, h in ACCENTS}
        for name, hexv in ACCENTS:
            b = Gtk.Button(tooltip_text=name, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            b.add_css_class("swatch")
            b.add_css_class(f"swatch-{hexv}")
            if hexv == s.accent:
                b.add_css_class("current")
            set_accessible_label(b, f"Accent colour {name}")
            b.connect("clicked", lambda *_, h=hexv: self._set_accent(h))
            row.append(b)
        if s.accent not in presets:
            b = Gtk.Button(tooltip_text="Custom", halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            b.add_css_class("swatch")
            b.add_css_class(f"swatch-{s.accent}")
            b.add_css_class("current")
            set_accessible_label(b, "Custom accent colour")
            row.append(b)
        box.append(row)
        exp = Gtk.Expander(label="Custom colour")
        exp.set_child(ColourPicker(tuple(bytes.fromhex(s.accent)), lambda rgb: self._set_accent(bytes(rgb).hex()),
                                   apply_label="Use this colour"))
        box.append(exp)
        return box

    def _set_accent(self, hexv):
        self.app.change(accent=hexv)
        GLib.idle_add(lambda: (self._build_settings(), False)[1])

    def _group_row(self, title, explanation, options, current, on_change) -> Gtk.Widget:
        row = vbox(8)
        row.append(label(title, "heading"))
        row.append(label(explanation, "small", "dim"))
        group = hbox(2, "group")
        group.set_halign(Gtk.Align.START)
        first = None
        for value, text in options:
            b = Gtk.ToggleButton(label=text, active=(value == current))
            set_accessible_label(b, f"{title}: {text}")
            if first:
                b.set_group(first)
            first = first or b
            b.connect("toggled", lambda btn, v=value: btn.get_active() and on_change(v))
            group.append(b)
        row.append(group)
        return row


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)   # DEFAULT_FLAGS needs GLib 2.74
        self.settings = settings_mod.load()
        self.provider = Gtk.CssProvider()
        self.portal_dark = None
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self.provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.gtk_settings = Gtk.Settings.get_default()
        self.desktop_animations = self.gtk_settings.get_property("gtk-enable-animations")
        self._watch_portal()
        self.apply_style()
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(desktop.RESOURCES)
        Gtk.Window.set_default_icon_name(APP_ID)
        self.sync_launcher()

    def sync_launcher(self):
        """Keep (or remove) the launcher entry for the AppImage this was started from."""
        path = desktop.appimage_path()
        try:
            desktop.remove_legacy()
            if self.settings.desktop_entry and path:
                desktop.install(path)
            elif not self.settings.desktop_entry:
                desktop.remove()
        except OSError as e:
            print(f"k609-keyboard-control: couldn't update the launcher entry: {e}", file=sys.stderr)

    def do_activate(self):
        if not self.window:
            self.window = Window(self)
        self.window.present()
        if os.environ.get("K609_SMOKE_TEST"):
            GLib.timeout_add(1500, self._smoke_done)

    def _smoke_done(self):
        w = self.window
        ok = bool(w and w.get_mapped() and w.get_width() > 100 and w.get_height() > 100)
        print(f"smoke test {'ok' if ok else 'FAILED'}: GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}."
              f"{Gtk.get_micro_version()}, Python {sys.version.split()[0]}, window {w.get_width()}x{w.get_height()}")
        self.smoke_ok = ok
        self.quit()
        return False

    def _watch_portal(self):
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION)
            reply = bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                                  "org.freedesktop.portal.Settings", "ReadOne",
                                  GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                                  None, Gio.DBusCallFlags.NONE, 1000, None)
            value = reply.unpack()[0]
            self.portal_dark = value == 1

            def changed(_c, _s, _p, _i, _sig, params):
                ns, key, val = params.unpack()
                if ns == "org.freedesktop.appearance" and key == "color-scheme":
                    self.portal_dark = val == 1
                    self.apply_style()
            bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Settings",
                                 "SettingChanged", "/org/freedesktop/portal/desktop", None,
                                 Gio.DBusSignalFlags.NONE, changed)
        except GLib.Error:
            self.portal_dark = None

    def is_dark(self) -> bool:
        if self.settings.theme == "dark":
            return True
        if self.settings.theme == "light":
            return False
        if self.portal_dark is not None:
            return self.portal_dark
        return bool(self.gtk_settings.get_property("gtk-application-prefer-dark-theme"))

    def apply_style(self):
        reduce = self.settings.reduce_motion or not self.desktop_animations
        self.gtk_settings.set_property("gtk-enable-animations", not reduce)
        css = stylesheet(self.is_dark(), self.settings.size, reduce, self.settings.accent)
        if hasattr(self.provider, "load_from_string"):          # GTK 4.12+
            self.provider.load_from_string(css)
        else:
            try:
                self.provider.load_from_data(css, -1)              # GTK 4.0-4.8: (text, length)
            except TypeError:
                self.provider.load_from_data(css.encode())         # GTK 4.10-4.11: bytes

    def change(self, **values):
        for k, v in values.items():
            setattr(self.settings, k, v)
        self.apply_style()
        try:
            settings_mod.save(self.settings)
        except OSError as e:
            print(f"k609-keyboard-control: couldn't save settings: {e}", file=sys.stderr)


def main() -> int:
    app = App()
    status = app.run([sys.argv[0]])
    if os.environ.get("K609_SMOKE_TEST"):
        return 0 if getattr(app, "smoke_ok", False) else 1
    return status
