"""Letting the logged-in user open the keyboard's settings interface.

Only when the user presses "Allow access": pkexec asks for an administrator password, then writes
device.UDEV_RULE (interface 1 of 258a:0049 only, uaccess) and reloads udev. Nothing else runs as root.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from .device import UDEV_RULE

RULE_PATH = "/etc/udev/rules.d/70-horus-control.rules"
SCRIPT = ('printf "%s" "$1" > "$2" && chmod 644 "$2" && udevadm control --reload '
          '&& udevadm trigger --subsystem-match=hidraw --action=change')


def host_env() -> dict[str, str]:
    """The environment without the AppImage's own library paths (see packaging/AppRun)."""
    env = dict(os.environ)
    for key, value in os.environ.items():
        if key.startswith("K609_HOST_"):
            name = key[len("K609_HOST_"):]
            env.pop(key)
            if value == "__unset__":
                env.pop(name, None)
            else:
                env[name] = value
    return env


def command() -> list[str]:
    return ["pkexec", "/bin/sh", "-c", SCRIPT, "sh", UDEV_RULE, RULE_PATH]


def can_install() -> bool:
    return shutil.which("pkexec", path=host_env().get("PATH")) is not None


def install(run=subprocess.run) -> str:
    """'done', 'cancelled' (password prompt closed or refused), 'missing' (no pkexec) or 'failed'."""
    try:
        r = run(command(), env=host_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
    except FileNotFoundError:
        return "missing"
    except (OSError, subprocess.TimeoutExpired):
        return "failed"
    if r.returncode == 0:
        return "done"
    return "cancelled" if r.returncode in (126, 127) else "failed"
