"""Horus Control GTK 4 window. Never touches HID directly; uses device/hidraw helpers off the main thread."""

from __future__ import annotations

import os
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, capabilities, lighting, settings as settings_mod  # noqa: E402
from .device import CONFIG_INTERFACE, UDEV_RULE, Keyboard, find_keyboards  # noqa: E402
from .hidraw import AccessDenied, DeviceGone, WriteFailed, describe_diff, diff_blocks, hexdump, read_lighting_block  # noqa: E402
from .style import stylesheet  # noqa: E402

APP_ID = "io.github.hypesthyper.HorusControl"
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


class Window(Gtk.ApplicationWindow):
    def __init__(self, app: "App"):
        super().__init__(application=app, title="Horus Control")
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
        self.previous_block = None              # (devnode, bytes) of the last good read
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
        icon = Gtk.Image.new_from_icon_name("input-keyboard-symbolic")
        icon.set_pixel_size(22)
        icon.add_css_class("app-icon")
        icon.set_valign(Gtk.Align.CENTER)
        header.append(icon)
        header.append(label("Horus Control", "app-title", wrap=False))
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
        self.light_state = None                 # (devnode, lighting.State) once loaded
        self.light_busy = False
        self.light_message = ("", "dim")
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
                result = find_keyboards(os.environ.get("HORUS_CONTROL_SYSFS", "/sys"))
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
        self.render()
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
        page.append(section("Lighting settings", "Reads the keyboard's lighting settings the same way "
                                                 "Redragon's software does. Nothing is changed."))
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
        box.append(label("Connect the Horus SE K609GG with its USB cable. Horus Control checks "
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
        card.append(label("Horus Control never opens the typing interface (interface 0) and never "
                          "reads your keystrokes.", "small", "faint"))
        return card

    def _access_card(self, iface) -> Gtk.Widget:
        card = vbox(10, "card")
        card.append(label("Your user can't open the configuration interface", "heading"))
        card.append(label(f"{iface.devnode} is owned by root, so settings can't be read. You can allow "
                          "it yourself with a udev rule that covers only this keyboard's interface 1. "
                          "Horus Control doesn't change system files.", "small", "dim"))
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
                          "press Enter. Horus Control reads the settings and adds what changed to your "
                          "list.", "small", "dim"))
        if (parent := self.note_entry.get_parent()) is not None:
            parent.remove(self.note_entry)
        self.note_entry.set_sensitive(iface.access)
        card.append(self.note_entry)
        row = hbox(12)
        read = Gtk.Button(label="Reading…" if self.reading else "Read lighting settings")
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
                head.append(label(f"Lighting settings · {len(res.data)} bytes", "heading", wrap=False))
                if res.ok:
                    head.append(chip("Read", "ok"))
                else:
                    head.append(chip("Problem", "error", "dialog-error-symbolic"))
                inner.append(head)
                if res.problem:
                    inner.append(label(res.problem, "small", "error-text"))
                if res.ok:
                    grid = Gtk.Grid(column_spacing=20, row_spacing=6)
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
            c = chip("On the Lighting tab", "ok") if usable else chip("Not yet verified", "neutral")
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

        def work():
            try:
                res, msg = [read_lighting_block(devnode)], ""
            except AccessDenied:
                res, msg = None, "Access denied. See the instructions above."
            except DeviceGone:
                res, msg = None, "The keyboard was disconnected during the read."
            except OSError as e:
                res, msg = None, f"Couldn't open {devnode}: {e.strerror}."
            GLib.idle_add(self._read_done, devnode, res, msg)
        threading.Thread(target=work, daemon=True).start()

    def _read_done(self, devnode, results, message):
        self.reading = False
        if results is not None:
            self.feature_results = (devnode, results)
            res = results[0]
            if res.ok:
                if self.previous_block and self.previous_block[0] == devnode:
                    self.last_change = describe_diff(diff_blocks(self.previous_block[1], res.data))
                else:
                    self.last_change = None
                self.previous_block = (devnode, res.data)
                n = len(self.change_log) + 1
                changes = ("first read" if self.last_change is None
                           else f"changed {self.last_change}" if self.last_change else "no change")
                self.change_log.append(f"{n}. {self.pending_note or '(no name)'}: bytes 20–21 = "
                                       f"{res.data[20]:02x} {res.data[21]:02x}; {changes}")
                self.note_entry.set_text("")
            message = "Read the lighting settings." if results[0].ok else "The read didn't work."
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
        lines = [f"Horus Control {__version__}", f"{kb.label} {kb.vendor_id:04x}:{kb.product_id:04x} "
                 f"bcdDevice {kb.bcd_device} USB {kb.usb_version}"]
        for i in kb.interfaces:
            lines.append(f"interface {i.interface_number}: {i.devnode} descriptor "
                         + " ".join(f"{b:02x}" for b in i.descriptor_bytes))
        if self.feature_results:
            for r in self.feature_results[1]:
                lines.append(f"Lighting block (SET_FEATURE 05 83 c6 00 00 00, then GET_FEATURE 0x06): "
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
            card.append(label("Horus Control can't open the keyboard yet. The Keyboard tab shows how to "
                              "allow it.", "dim"))
            return

        if self.light_state is None:
            card.append(label("Read the current effect, brightness and speed from the keyboard.", "small", "dim"))
            load = Gtk.Button(label="Reading…" if self.light_busy else "Load current lighting")
            load.add_css_class("filled")
            load.set_halign(Gtk.Align.START)
            load.set_sensitive(not self.light_busy)
            load.connect("clicked", lambda *_: self._light_run(
                lambda: lighting.read_state(iface.devnode), lambda st: ""))
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
            if st.effect == lighting.SELF_DEFINE:
                effect_box.append(label("Shows the per-key colours set in Redragon's software.", "small", "dim"))
            card.append(effect_box)
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
                card.append(label(f"{st.name} has no brightness or speed setting.", "small", "dim"))

        text, kind = self.light_message
        if text:
            card.append(label(text, "small", kind))

        saved = lighting.load_backup(lighting.backup_path())
        page.append(section("Restore", None))
        rc = vbox(10, "card")
        if saved:
            rc.append(label("Puts back the effect, brightness and speed the keyboard had before your first "
                            f"change in Horus Control (saved {saved[0].replace('T', ' at ')}).", "small", "dim"))
            btn = Gtk.Button(label="Restore")
            btn.set_halign(Gtk.Align.START)
            btn.set_sensitive(not self.light_busy)
            btn.connect("clicked", lambda *_: self._light_run(
                lambda: lighting.restore(iface.devnode, lighting.backup_path(), self._known_colour()),
                lambda st: f"Restored {st.name}."))
            rc.append(btn)
        else:
            rc.append(label("Before your first change, Horus Control saves the keyboard's effect, brightness "
                            "and speed so you can put them back here.", "small", "dim"))
        page.append(rc)
        page.append(label("Colour can't be changed yet: it's stored in a part of the keyboard Horus Control "
                          "can't read yet.", "small", "faint"))

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
            b.connect("clicked", lambda *_, h=hexv, n=name: self._send_colour(iface, h, n.lower()))
            swatches.append(b)
        box.append(swatches)
        row = hbox(10)
        entry = Gtk.Entry(placeholder_text="Hex, like ff8800", max_length=7, width_chars=12)
        entry.add_css_class("colour-entry")
        set_accessible_label(entry, "Fixed on colour as a hex code")
        apply_btn = Gtk.Button(label="Apply colour")
        apply_btn.set_sensitive(not self.light_busy)

        def from_entry(*_):
            try:
                rgb = lighting.parse_hex_colour(entry.get_text())
            except ValueError as e:
                self.light_message = (str(e), "error-text")
                self.render()
                return
            self._send_colour(iface, bytes(rgb).hex(), "#" + bytes(rgb).hex())
        entry.connect("activate", from_entry)
        apply_btn.connect("clicked", from_entry)
        row.append(entry)
        row.append(apply_btn)
        box.append(row)
        return box

    def _send_colour(self, iface, hexv, name):
        if self.light_busy:
            return
        rgb = tuple(bytes.fromhex(hexv))

        def job():
            st = lighting.set_fixed_colour(iface.devnode, rgb)
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
        self._light_run(lambda: lighting.apply(iface.devnode, backup=lighting.backup_path(),
                                               colour=colour, **change),
                        lambda st: message)

    def _known_colour(self):
        """The Fixed on colour last sent from here, so saves can include it as the official
        software does. None if Horus Control has never set one: the table isn't sent then."""
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
        page.append(card)

        page.append(section("About", None))
        about = vbox(6, "card")
        about.append(label(f"Horus Control {__version__}", "heading"))
        about.append(label("A read-only inspector for the Redragon Horus SE K609GG over wired USB. "
                           "Settings are saved in ~/.config/horus-control/.", "small", "dim"))
        page.append(about)

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
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
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

    def do_activate(self):
        if not self.window:
            self.window = Window(self)
        self.window.present()

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
        css = stylesheet(self.is_dark(), self.settings.size, reduce)
        if hasattr(self.provider, "load_from_string"):
            self.provider.load_from_string(css)
        else:
            self.provider.load_from_data(css, -1)

    def change(self, **values):
        for k, v in values.items():
            setattr(self.settings, k, v)
        self.apply_style()
        try:
            settings_mod.save(self.settings)
        except OSError as e:
            print(f"horus-control: couldn't save settings: {e}", file=sys.stderr)


def main() -> int:
    return App().run(sys.argv)
