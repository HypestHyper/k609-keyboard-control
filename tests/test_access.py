import subprocess

from k609_control import access
from k609_control.device import UDEV_RULE


def test_command_writes_only_the_rule():
    cmd = access.command()
    assert cmd[:2] == ["pkexec", "/bin/sh"] and cmd[-2:] == [UDEV_RULE, access.RULE_PATH]
    assert "uaccess" in UDEV_RULE and 'ATTRS{bInterfaceNumber}=="01"' in UDEV_RULE and "MODE" not in UDEV_RULE


def test_results():
    def run(code):
        return lambda *a, **k: subprocess.CompletedProcess(a, code)
    assert access.install(run(0)) == "done"
    assert access.install(run(126)) == "cancelled"
    assert access.install(run(1)) == "failed"

    def missing(*a, **k):
        raise FileNotFoundError
    assert access.install(missing) == "missing"


def test_host_env(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/appimage/usr/lib")
    monkeypatch.setenv("K609_HOST_LD_LIBRARY_PATH", "__unset__")
    monkeypatch.setenv("PYTHONHOME", "/appimage/usr")
    monkeypatch.setenv("K609_HOST_PYTHONHOME", "/host")
    env = access.host_env()
    assert "LD_LIBRARY_PATH" not in env and env["PYTHONHOME"] == "/host"
    assert not any(k.startswith("K609_HOST_") for k in env)
