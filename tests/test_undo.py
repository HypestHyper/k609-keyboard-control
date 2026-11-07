from test_profiles import WholeKeyboard

from k609_control import keymap, lighting, macros, profiles, undo
from k609_control.macros import Macro, Step


def test_undo_puts_keys_macros_and_lighting_back():
    kb = WholeKeyboard()
    io = kb.io()
    keymap.remap("/dev/x", {"Caps Lock": 0xE0}, **io)
    ms = [Macro("ab", [Step(4, True, 30), Step(4, False, 30)], key="Page Down")]
    macros.apply("/dev/x", ms, **io)
    before = undo.Snapshot("test", light=(lighting.read_state("/dev/x", **io), "ff8000"),
                           keys=keymap.read("/dev/x", **io), macros=undo.copy_macros(ms))

    lighting.apply("/dev/x", effect=0x03, **io)
    keymap.reset_all("/dev/x", **io)
    macros.apply("/dev/x", [], **io)
    keymap.remap("/dev/x", {"A": 0x05}, **io)

    undo.restore("/dev/x", before, **io)
    cur = keymap.current(kb.keymap)
    assert cur["Caps Lock"] == 0xE0 and cur["A"] == 0x04
    assert keymap.entries(kb.keymap)[94] == bytes.fromhex("10000118")
    assert kb.lighting[21] == 0x0B and kb.colour_table[29:32] == bytes.fromhex("ff8000")


def test_only_recorded_parts_are_written():
    kb = WholeKeyboard()
    io = kb.io()
    snap = undo.Snapshot("remap A", keys=keymap.read("/dev/x", **io))
    keymap.remap("/dev/x", {"A": 0x05}, **io)
    kb.writes.clear()
    undo.restore("/dev/x", snap, **io)
    assert kb.writes == ["0604d8"]
    assert keymap.current(kb.keymap)["A"] == 0x04


def test_profile_files_are_put_back(tmp_path):
    p = profiles.Profile("Work", 1, {e: 0x44 for e in range(1, 0x13)}, None, {"A": 4})
    profiles.save(p, str(tmp_path))
    undo.restore_files(undo.Snapshot("delete Work", profile_file=p), str(tmp_path))
    assert profiles.find("Work", str(tmp_path)).to_dict() == p.to_dict()
    undo.restore_files(undo.Snapshot("save Work", profile_created="Work"), str(tmp_path))
    assert profiles.find("Work", str(tmp_path)) is None
    assert not undo.Snapshot("x", profile_created="Work").needs_keyboard
