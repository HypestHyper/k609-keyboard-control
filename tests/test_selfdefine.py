import pytest
from test_lighting import block
from test_profiles import WholeKeyboard

from k609_control import hidraw, keymap, lighting, selfdefine


def test_recorded_positions():
    # User's recording (2026-11-06): Esc red, A green, Space blue, Right white changed these bytes.
    t = selfdefine.build_colour_table({1: (255, 0, 0), 9: (0, 255, 0), 35: (0, 0, 255), 95: (255, 255, 255)})
    base = selfdefine.template("cc")
    changed = {i: t[i] for i in range(1032) if t[i] != base[i]}
    assert changed == {29: 0xFF, 198: 0xFF, 370: 0xFF, 128: 0xFF, 254: 0xFF, 380: 0xFF}


def test_every_key_has_a_colour_index():
    assert set(selfdefine.COLOUR_INDEX) == set(keymap.LAYOUT)
    assert len(set(selfdefine.COLOUR_INDEX.values())) == len(selfdefine.COLOUR_INDEX)
    assert max(selfdefine.COLOUR_INDEX.values()) < selfdefine.PLANE


def test_table_checks():
    t = selfdefine.build_colour_table({1: (1, 2, 3)})
    assert selfdefine.is_colour_table_write(t)
    bad = bytearray(t); bad[500] ^= 0xFF
    assert not selfdefine.is_colour_table_write(bytes(bad))
    assert selfdefine.is_second_table_write(selfdefine.template("d0"))
    assert not selfdefine.is_second_table_write(t)
    with pytest.raises(ValueError):
        selfdefine.build_colour_table({999: (1, 2, 3)})


class SelfDefineKeyboard(WholeKeyboard):
    def __init__(self):
        super().__init__()
        self.lighting = bytes(block(0x01))
        self.tables = []

    def ioctl(self, fd, request, buf, mutate):
        if request == hidraw.hidiocsfeature(1032) and bytes(buf[:2]) == b"\x06\x09":
            self.writes.append(bytes(buf[:3]).hex())
            self.tables.append(bytes(buf))
            return 1032
        return super().ioctl(fd, request, buf, mutate)


def test_apply_follows_official_sequence():
    kb = SelfDefineKeyboard()
    pauses = []
    io = kb.io(); io["sleep"] = pauses.append
    st = selfdefine.apply("/dev/x", {1: (255, 0, 0)}, **io)
    assert st.effect == lighting.SELF_DEFINE and kb.lighting[20] == 1
    assert kb.writes == ["0609cc", "0609d0", "0603c6"]
    assert pauses[:3] == [0.02, 0.02, 0.05]   # read command gap, before tables, between tables
    assert kb.tables[0][29] == 0xFF and kb.tables[1] == selfdefine.template("d0")


def test_storage_roundtrip(tmp_path):
    colours = {1: (255, 0, 0), 35: (0, 0, 255), 9: (0, 0, 0)}
    selfdefine.save(colours, str(tmp_path / "s.json"))
    assert selfdefine.load(str(tmp_path / "s.json")) == {1: (255, 0, 0), 35: (0, 0, 255)}
