import os

import pytest

from horus_control import hidraw, keymap

# The key map read from the user's keyboard on 2026-11-06, default layout.
DEFAULT = bytes.fromhex(open(os.path.join(os.path.dirname(__file__), "keymap_default.hex")).read())


def caps_default():
    return DEFAULT


def caps_as_esc():
    """As the official software saved it after remapping Caps Lock to Esc (entry 143: 39 -> 29)."""
    b = bytearray(DEFAULT)
    b[8 + 4 * 143 + 3] = 0x29
    return bytes(b)


def test_rule_places_every_key_on_its_default_code():
    keymap.check(caps_default())
    cur = keymap.current(caps_default())
    assert len(cur) == 60
    assert all(cur[k.name] == k.default for k in keymap.REMAPPABLE)


def test_recorded_remaps():
    assert {k.name: k.entry for k in keymap.KEYS}["Caps Lock"] == 143
    assert {k.name: k.entry for k in keymap.KEYS}["Esc"] == 147
    assert keymap.current(caps_as_esc())["Caps Lock"] == 0x29


def test_build_write_matches_official_save():
    # The official software saved Caps Lock -> Esc as: write header, then the map with entry 143 changed.
    w = keymap.build_write(caps_default(), {"Caps Lock": 0x29})
    assert w[:8] == bytes.fromhex("0604d80040000000") and len(w) == 1032
    assert w[8:] == caps_as_esc()[8:]
    assert hidraw.is_keymap_write(w)


def test_build_write_refuses_unsupported():
    with pytest.raises(ValueError):
        keymap.build_write(caps_default(), {"Left Shift": 0x04})
    with pytest.raises(ValueError):
        keymap.build_write(caps_default(), {"A": 0xE0})
    bad = bytearray(caps_default()); bad[8 + 4 * 3] = 0x00          # Caps Lock pointer broken
    with pytest.raises(keymap.UnexpectedKeymap):
        keymap.build_write(bytes(bad), {"A": 0x05})
    with pytest.raises(keymap.UnexpectedKeymap):
        keymap.check(bytes.fromhex("0683c6") + bytes(1029))


def test_keymap_write_shape():
    w = keymap.build_write(caps_default(), {"A": 0x05})
    assert hidraw.is_keymap_write(w)
    assert not hidraw.is_keymap_write(w[:-1])
    assert not hidraw.is_keymap_write(bytes.fromhex("0603c6") + w[3:])
    odd = bytearray(w); odd[8] = 0x77
    assert not hidraw.is_keymap_write(bytes(odd))


class FakeKeyboard:
    def __init__(self, data, keep=True):
        self.data = bytearray(data)
        self.keep = keep
        self.sequence = []

    def ioctl(self, fd, request, buf, mutate):
        self.sequence.append(bytes(buf[:3]).hex())
        if request == hidraw.hidiocsfeature(6):
            assert bytes(buf) == hidraw.READ_KEYMAP
            return 6
        if request == hidraw.hidiocsfeature(1032):
            assert hidraw.is_keymap_write(bytes(buf))
            if self.keep:
                self.data = bytearray(hidraw.KEYMAP_REPLY_PREFIX + bytes([0, 0x84]) + bytes(buf[5:]))
            return 1032
        if request == hidraw.hidiocgfeature(1032):
            buf[:] = self.data
            return 1032
        raise AssertionError(hex(request))

    def io(self):
        return dict(opener=lambda p, f: 3, ioctl=self.ioctl, closer=lambda fd: None, sleep=lambda s: None)


def test_remap_reads_saves_once_and_verifies():
    kb = FakeKeyboard(caps_default())
    now = keymap.remap("/dev/x", {"Caps Lock": 0x29}, **kb.io())
    assert now["Caps Lock"] == 0x29
    assert kb.sequence == ["0584d8", "060000", "0604d8", "0584d8", "060000"]
    assert bytes(kb.data[8:]) == caps_as_esc()[8:]


def test_reset_all_restores_defaults():
    kb = FakeKeyboard(caps_as_esc())
    now = keymap.reset_all("/dev/x", **kb.io())
    assert all(now[k.name] == k.default for k in keymap.REMAPPABLE)
    assert bytes(kb.data[8:]) == caps_default()[8:]


def test_remap_not_kept():
    kb = FakeKeyboard(caps_default(), keep=False)
    with pytest.raises(keymap.VerifyFailed):
        keymap.remap("/dev/x", {"A": 0x05}, **kb.io())


def test_read_header_from_keyboard():
    assert DEFAULT[:8] == keymap.READ_HEADER


def test_layout_covers_every_key():
    assert set(keymap.LAYOUT) == {k.number for k in keymap.KEYS} | set(keymap.SPECIAL)
    for x1, y1, x2, y2 in keymap.LAYOUT.values():
        assert 16 <= x1 < x2 <= 606 and 54 <= y1 < y2 <= 232
