import json

import pytest
from test_keymap import FakeKeyboard, caps_default

from horus_control import hidraw, keymap, macros
from horus_control.macros import Macro, Step

A, B, C, D = 0x04, 0x05, 0x06, 0x07


def ab_macro():
    return Macro("test", [Step(A, True, 50), Step(A, False, 200), Step(B, True, 50), Step(B, False, 0)])


def recorded(hexstr):
    data = bytes.fromhex(hexstr)
    return data + bytes(128 - len(data))


def test_slots_match_recorded_saves():
    # Recorded from the official software (user's captures, 2026-11-06).
    assert macros.encode_slot(ab_macro()) == recorded("00 01 32 04 83 04 00 03 00 02 32 05 83 05")
    m = Macro("test", [Step(A, True, 50), Step(A, False, 500), Step(B, True, 500), Step(B, False, 0)], count=3)
    assert macros.encode_slot(m) == recorded("00 03 32 04 83 04 00 03 00 05 03 05 00 03 00 05 83 05")
    m2 = Macro("test2", [Step(C, True, 20), Step(C, False, 1000), Step(D, True, 20), Step(D, False, 0)], count=2)
    assert macros.encode_slot(m2) == recorded("00 02 14 06 83 06 00 03 00 0a 14 07 83 07")


def test_block_layout_matches_recording():
    m2 = Macro("test2", [Step(C, True, 20), Step(C, False, 1000), Step(D, True, 20), Step(D, False, 0)], count=2)
    m = Macro("test", [Step(A, True, 50), Step(A, False, 500), Step(B, True, 500), Step(B, False, 0)], count=3)
    block = macros.build_block([m2, m])
    assert block[:8] == bytes.fromhex("0605e80040000000") and len(block) == 1032
    assert block[8:8 + 128] == recorded("00 02 14 06 83 06 00 03 00 0a 14 07 83 07")
    assert block[136:136 + 128] == recorded("00 03 32 04 83 04 00 03 00 05 03 05 00 03 00 05 83 05")
    assert hidraw.is_macro_write(block)
    assert macros.key_entry(Macro("x", [Step(A, True)], held=False), 0) == bytes.fromhex("10000118")
    assert macros.key_entry(Macro("x", [Step(A, True)], held=True), 1) == bytes.fromhex("10000419")


def test_validation():
    with pytest.raises(ValueError):
        macros.validate(Macro("x", [Step(A, True, 150)]))      # not a multiple of 100
    with pytest.raises(ValueError):
        macros.validate(Macro("", [Step(A, True)]))
    with pytest.raises(ValueError):
        macros.validate(Macro("x", []))
    with pytest.raises(ValueError):
        macros.validate(Macro("x", [Step(0xB5, True)]))        # media key not supported
    with pytest.raises(ValueError):
        macros.validate(Macro("x", [Step(A, True, 1000), Step(A, False, 1000)] * 20))
    with pytest.raises(ValueError):
        macros.build_block([ab_macro()] * 9)


class MacroKeyboard(FakeKeyboard):
    def __init__(self, data):
        super().__init__(data)
        self.macro_writes = []

    def ioctl(self, fd, request, buf, mutate):
        if request == hidraw.hidiocsfeature(1032) and bytes(buf[:3]) == bytes.fromhex("0605e8"):
            self.sequence.append("0605e8")
            assert hidraw.is_macro_write(bytes(buf))
            self.macro_writes.append(bytes(buf))
            return 1032
        return super().ioctl(fd, request, buf, mutate)


def test_apply_sequence_and_entries():
    kb = MacroKeyboard(caps_default())
    m2 = Macro("test2", [Step(C, True, 20), Step(C, False, 1000), Step(D, True, 20), Step(D, False, 0)],
               count=2, key="`")
    m = Macro("test", [Step(A, True, 50), Step(A, False, 500), Step(B, True, 500), Step(B, False, 0)],
              count=3, held=True, key="Page Down")
    cur = macros.apply("/dev/x", [m2, m], **kb.io())
    assert kb.sequence == ["0584d8", "060000", "0605e8", "0604d8", "0584d8", "060000"]
    e = keymap.entries(bytes(kb.data))
    assert e[92] == bytes.fromhex("10000118") and e[94] == bytes.fromhex("10000419")   # as recorded
    assert cur["`"] == keymap.MACRO_CODE and cur["Page Down"] == keymap.MACRO_CODE + 1
    # Unassigning resets the key and its stale macro entry.
    m2.key = None
    m.key = None
    macros.apply("/dev/x", [m2, m], **kb.io())
    assert keymap.entries(bytes(kb.data))[92] == bytes.fromhex("00000035")
    assert keymap.entries(bytes(kb.data))[94] == bytes.fromhex("0000004e")


def test_storage_roundtrip(tmp_path):
    path = str(tmp_path / "macros.json")
    m = ab_macro(); m.key = "Page Down"; m.held = True
    macros.save([m], path)
    assert macros.load(path)[0].to_dict() == m.to_dict()
    (tmp_path / "bad.json").write_text(json.dumps({"version": 1, "macros": [{"name": "x", "steps": [{"key": 4, "down": True, "pause": 150}]}]}))
    assert macros.load(str(tmp_path / "bad.json")) == []
