import json

import pytest
from test_keymap import caps_default
from test_lighting import block

from k609_control import hidraw, keymap, macros, profiles
from k609_control.macros import Macro, Step


class WholeKeyboard:
    """Fake keyboard with a lighting block, a key map and a macro block."""

    def __init__(self):
        self.lighting = bytes(block(0x0B))
        self.keymap = bytes(caps_default())
        self.macro_block = None
        self.colour_table = None
        self.last_cmd = None
        self.writes = []

    def ioctl(self, fd, request, buf, mutate):
        data = bytes(buf)
        if request == hidraw.hidiocsfeature(6):
            self.last_cmd = data
            return 6
        if request == hidraw.hidiocsfeature(1032):
            head = data[:3].hex()
            self.writes.append(head)
            if head == "0603c6":
                self.lighting = bytes([6, 0x83]) + data[2:262]
            elif head == "0604d8":
                self.keymap = hidraw.KEYMAP_REPLY_PREFIX + bytes([0, 0x84]) + data[5:]
            elif head == "0605e8":
                self.macro_block = data
            elif head == "0608c8":
                self.colour_table = data
            return 1032
        if request == hidraw.hidiocgfeature(1032):
            reply = self.lighting if self.last_cmd == hidraw.READ_LIGHTING else self.keymap
            buf[:len(reply)] = reply
            return len(reply)
        raise AssertionError(hex(request))

    def io(self):
        return dict(opener=lambda p, f: 3, ioctl=self.ioctl, closer=lambda fd: None, sleep=lambda s: None)


def test_capture_save_load_apply_roundtrip(tmp_path):
    kb = WholeKeyboard()
    io = kb.io()
    # set up a state: Caps Lock -> Ctrl, a macro on Page Down, effect Neon stream
    keymap.remap("/dev/x", {"Caps Lock": 0xE0}, **io)
    ms = [Macro("ab", [Step(4, True, 30), Step(4, False, 30)], key="Page Down")]
    macros.apply("/dev/x", ms, **io)
    p = profiles.capture("/dev/x", "Gaming", "ff8000", ms, **io)
    assert p.effect == 0x0B and p.keys["Caps Lock"] == 0xE0 and "Page Down" not in p.keys
    profiles.save(p, str(tmp_path))
    assert (tmp_path / "Gaming.json").exists()
    loaded = profiles.find("gaming", str(tmp_path))
    assert loaded.to_dict() == p.to_dict()

    # change everything, then apply the profile back
    keymap.reset_all("/dev/x", **io)
    macros.apply("/dev/x", [], **io)
    kb.writes.clear()
    profiles.apply("/dev/x", loaded, **io)
    cur = keymap.current(kb.keymap)
    assert cur["Caps Lock"] == 0xE0
    assert keymap.entries(kb.keymap)[94] == bytes.fromhex("10000118")      # Page Down plays slot 0
    assert kb.lighting[21] == 0x0B and kb.colour_table[29:32] == bytes.fromhex("ff8000")
    assert kb.writes[0] == "0608c8"


def test_bad_profiles_are_rejected(tmp_path):
    good = profiles.Profile("x", 1, {e: 0x44 for e in range(1, 0x13)}, None, {"A": 4})
    profiles.validate(good)
    for bad in (dict(effect=0x99), dict(colour="red"), dict(keys={"Fn": 4}), dict(keys={"A": 0xB5}),
                dict(levels={1: 0x55})):
        d = good.to_dict(); d.update({k: v for k, v in bad.items() if k != "levels"})
        if "levels" in bad:
            d["levels"] = {f"{k:02x}": v for k, v in bad["levels"].items()}
        with pytest.raises(ValueError):
            profiles.from_dict(json.loads(json.dumps(d)))
    (tmp_path / "junk.json").write_text("{nope")
    assert profiles.load_all(str(tmp_path)) == []


def test_file_names_are_safe():
    assert profiles.file_name("../../etc/passwd") == "etc-passwd.json"
    assert profiles.file_name("Work / Day") == "Work-Day.json"



def test_export_import(tmp_path):
    p = profiles.Profile("Work", 1, {e: 0x44 for e in range(1, 0x13)}, "00ff00", {"Caps Lock": 0xE0},
                         [Macro("ab", [Step(4, True, 30), Step(4, False, 30)], key="Page Down")])
    store = tmp_path / "store"
    out = tmp_path / "shared.json"
    profiles.export_to(p, str(out))
    first = profiles.import_from(str(out), str(store))
    second = profiles.import_from(str(out), str(store))
    assert first.name == "Work" and second.name == "Work 2"
    assert sorted(x.name for x in profiles.load_all(str(store))) == ["Work", "Work 2"]
    assert profiles.find("work 2", str(store)).keys == {"Caps Lock": 0xE0}
    (tmp_path / "bad.json").write_text(json.dumps({"version": 1, "name": "x"}))
    with pytest.raises(ValueError):
        profiles.import_from(str(tmp_path / "bad.json"), str(store))



def test_profile_keeps_selfdefine_colours(tmp_path):
    p = profiles.Profile("Paint", 0x15, {e: 0x44 for e in range(1, 0x13)}, None, {}, [], {1: (255, 0, 0)})
    profiles.save(p, str(tmp_path))
    assert profiles.find("Paint", str(tmp_path)).selfdef == {1: (255, 0, 0)}
