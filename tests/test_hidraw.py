import errno

import pytest
from fixtures import IFACE0, IFACE1

from horus_control import hidraw
from horus_control.hidraw import AccessDenied, DeviceGone, Report, parse_descriptor


def test_interface1_feature_reports_sized_from_descriptor():
    d = parse_descriptor(IFACE1)
    feats = {r.report_id: r for r in d.feature_reports()}
    assert set(feats) == {0x05, 0x06}
    assert feats[5].payload_len == 5 and feats[5].buffer_len == 6
    assert feats[6].payload_len == 1031 and feats[6].buffer_len == 1032
    assert 0x08 not in feats
    assert d.has_vendor_collection


def test_interface1_input_reports():
    d = parse_descriptor(IFACE1)
    inputs = {r.report_id: r.payload_len for r in d.reports if r.kind == "input"}
    assert inputs == {1: 1, 2: 2, 3: 3, 4: 15, 7: 7}


def test_interface0_is_plain_keyboard():
    d = parse_descriptor(IFACE0)
    assert not d.feature_reports()
    assert not d.has_vendor_collection
    assert d.collections[0].usage_page == 0x01 and d.collections[0].usage == 0x06


def test_truncated_descriptor_raises():
    with pytest.raises(hidraw.DescriptorError):
        parse_descriptor(IFACE1[:-3] + b"\x26\xff")


def test_ioctl_number_matches_linux_header():
    # _IOC(_IOC_WRITE|_IOC_READ, 'H', 0x07, 6) == 0xC0064807
    assert hidraw.hidiocgfeature(6) == 0xC0064807
    with pytest.raises(ValueError):
        hidraw.hidiocgfeature(0)


class FakeDevice:
    """Stands in for os.open/fcntl.ioctl/os.close. Records every request."""

    def __init__(self, replies=None, open_error=None, ioctl_error=None):
        self.replies = replies or {}
        self.open_error = open_error
        self.ioctl_error = ioctl_error
        self.requests = []
        self.closed = False
        self.flags = None

    def open(self, path, flags):
        if self.open_error:
            raise OSError(self.open_error, "fake")
        self.flags = flags
        return 42

    def ioctl(self, fd, request, buf, mutate):
        self.requests.append((request, len(buf), buf[0]))
        if self.ioctl_error:
            raise OSError(self.ioctl_error, "fake")
        reply = self.replies.get(buf[0], b"")
        buf[:len(reply)] = reply
        return len(reply)

    def close(self, fd):
        self.closed = True

    def run(self, reports):
        return hidraw.read_feature_reports("/dev/hidrawX", reports, opener=self.open,
                                           ioctl=self.ioctl, closer=self.close)


def test_reads_use_get_feature_only_and_close():
    dev = FakeDevice({5: bytes([5, 1, 2, 3, 4, 5])})
    res = dev.run([Report("feature", 5, 40)])
    assert res[0].ok and res[0].data == bytes([5, 1, 2, 3, 4, 5])
    assert dev.requests == [(hidraw.hidiocgfeature(6), 6, 5)]
    assert all((req >> 8) & 0xFF == ord("H") and req & 0xFF == 0x07 for req, _, _ in dev.requests)
    assert dev.closed


def test_short_and_malformed_replies_are_flagged():
    dev = FakeDevice({5: bytes([5, 1]), 6: bytes([9, 0, 0])})
    short, wrong = dev.run([Report("feature", 5, 40), Report("feature", 6, 16)])
    assert "Short reply" in short.problem
    assert "report ID 0x09" in wrong.problem
    assert not FakeDevice({}).run([Report("feature", 5, 40)])[0].ok


def test_permission_denied():
    with pytest.raises(AccessDenied):
        FakeDevice(open_error=errno.EACCES).run([Report("feature", 5, 40)])


def test_unplug_during_read():
    dev = FakeDevice(ioctl_error=errno.ENODEV)
    with pytest.raises(DeviceGone):
        dev.run([Report("feature", 5, 40)])
    assert dev.closed


def test_device_stall_is_a_per_report_error():
    res = FakeDevice(ioctl_error=errno.EPIPE).run([Report("feature", 5, 40)])
    assert res[0].problem.startswith("Read failed")


def test_module_has_no_write_paths():
    import inspect
    src = inspect.getsource(hidraw)
    assert "os.write" not in src and "0x06, len" not in src and "HIDIOCSFEATURE" not in src
