import json

import pytest

from horus_control import hidraw, lighting

# The real block read from the user's keyboard on 2026-11-06 (effect Self define).
REAL_DUMP = """
0000  06 83 c6 00 00 00 00 00 00 00 00 00 00 00 5a a5
0010  03 03 00 00 01 15 20 03 00 00 00 00 55 55 01 00
0020  00 01 00 00 ff ff 00 44 07 44 07 44 07 44 07 44
0030  07 44 07 44 07 44 07 44 07 44 07 44 07 44 07 44
0040  07 44 07 44 07 44 07 44 07 44 07 44 07 44 5a a5
0050  00 00 07 44 07 44 07 44 07 44 07 44 07 44 07 44
0060  04 04 04 04 04 04 04 04 04 04 00 00 00 00 00 00
0070  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0080  00 00 00 00 00 00 00 00 00 5a a5 03 03 00 00 00
0090  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00a0  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00b0  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00c0  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00d0  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00e0  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
00f0  00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0100  00 00 00 00 00 00
"""
REAL = bytes.fromhex("".join(line[6:] for line in REAL_DUMP.strip().splitlines()))
assert len(REAL) == 262


def block(effect=0x01, custom=0, **levels):
    b = bytearray(REAL)
    b[20], b[21] = custom, effect
    for e, v in levels.items():
        b[lighting.level_offset(int(e[1:], 16))] = v
    return bytes(b)


def test_real_block_parses():
    st = lighting.parse(REAL)
    assert st.name == "Self define" and st.brightness is None and st.speed is None
    st = lighting.parse(block(0x03))
    assert (st.name, st.brightness, st.speed) == ("Rainbow", 4, 4)


def test_level_offsets_match_observations():
    assert lighting.level_offset(0x01) == 39
    assert lighting.level_offset(0x03) == 43
    assert lighting.level_offset(0x0B) == 59
    assert lighting.level_offset(0x00) is None and lighting.level_offset(0x15) is None


def test_build_write_changes_only_known_fields():
    src = block(0x01)
    w = lighting.build_write(src, effect=0x03)
    assert hidraw.is_lighting_write(w)
    assert w[:3] == bytes.fromhex("0603c6") and w[21] == 0x03 and w[20] == 0
    assert [i for i in range(3, 262) if w[i] != src[i]] == [21]
    w = lighting.build_write(src, brightness=2)
    assert w[39] == 0x42 and [i for i in range(3, 262) if w[i] != src[i]] == [39]
    w = lighting.build_write(src, speed=0)
    assert w[39] == 0x04
    w = lighting.build_write(src, effect=lighting.SELF_DEFINE)
    assert (w[20], w[21]) == (1, 0x15)


def test_build_write_rejects_bad_input():
    with pytest.raises(ValueError):
        lighting.build_write(block(0x01), brightness=5)
    with pytest.raises(ValueError):
        lighting.build_write(block(0x01), effect=0x13)
    with pytest.raises(ValueError):
        lighting.build_write(block(0x00), brightness=1)       # Off has no level byte
    for bad in (block(0x13), block(0x01, custom=1), block(0x01, e01=0x55), REAL[:100]):
        with pytest.raises(lighting.UnexpectedBlock):
            lighting.build_write(bad, effect=0x01)


class FakeKeyboard:
    """Keeps a block; answers the read command and accepts lighting writes."""

    def __init__(self, data, keep=True):
        self.data = bytes(data)
        self.keep = keep
        self.writes = []

    def ioctl(self, fd, request, buf, mutate):
        if request == hidraw.hidiocsfeature(6):
            assert bytes(buf) == hidraw.READ_LIGHTING
            return 6
        if request == hidraw.hidiocsfeature(1032):
            self.writes.append(bytes(buf))
            if self.keep:
                self.data = bytes([6, 0x83]) + bytes(buf[2:262])
            return 1032
        if request == hidraw.hidiocgfeature(1032):
            buf[:262] = self.data
            return 262
        raise AssertionError(hex(request))

    def io(self):
        return dict(opener=lambda p, f: 3, ioctl=self.ioctl, closer=lambda fd: None, sleep=lambda s: None)


def test_apply_writes_verifies_and_backs_up(tmp_path):
    kb = FakeKeyboard(block(0x01))
    path = str(tmp_path / "lighting-backup.json")
    st = lighting.apply("/dev/x", backup=path, effect=0x0B, **kb.io())
    assert st.name == "Neon stream" and len(kb.writes) == 1
    saved = json.loads(open(path).read())
    assert saved["effect"] == 0x01 and saved["levels"]["01"] == 0x44
    st = lighting.apply("/dev/x", backup=path, brightness=1, speed=3, **kb.io())
    assert (st.brightness, st.speed) == (1, 3) and kb.data[59] == 0x31
    assert json.loads(open(path).read())["effect"] == 0x01     # first backup kept


def test_apply_without_change_does_not_write():
    kb = FakeKeyboard(block(0x03))
    lighting.apply("/dev/x", effect=0x03, **kb.io())
    assert kb.writes == []


def test_apply_reports_change_not_kept():
    kb = FakeKeyboard(block(0x01), keep=False)
    with pytest.raises(lighting.VerifyFailed):
        lighting.apply("/dev/x", effect=0x02, **kb.io())


def test_restore_puts_back_known_fields(tmp_path):
    kb = FakeKeyboard(block(0x03, e03=0x21))
    path = str(tmp_path / "b.json")
    lighting.apply("/dev/x", backup=path, effect=0x05, **kb.io())
    lighting.apply("/dev/x", backup=path, brightness=0, **kb.io())
    st = lighting.restore("/dev/x", path, **kb.io())
    assert st.name == "Rainbow" and (st.brightness, st.speed) == (1, 2)
    assert kb.data[3:] == block(0x03, e03=0x21)[3:]


def test_bad_backup_is_refused(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"version": 1, "effect": 1, "levels": {"01": 0x99}}))
    assert lighting.load_backup(str(path)) is None
    with pytest.raises(FileNotFoundError):
        lighting.restore("/dev/x", str(path), **FakeKeyboard(block()).io())
