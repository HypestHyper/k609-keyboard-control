"""The app's own launcher entry (~/.local/share/applications), written when run as an AppImage.

Only per-user files are written: the .desktop entry and the icon. Nothing system-wide.
"""

from __future__ import annotations

import os
import shutil

from . import APP_ID, COMMENT, KEYWORDS, LAUNCHER_NAME  # noqa: F401  (LAUNCHER_NAME is used by the app)

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
ICON_SOURCE = os.path.join(RESOURCES, f"{APP_ID}.svg")


def data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def entry_path() -> str:
    return os.path.join(data_home(), "applications", f"{APP_ID}.desktop")


def icon_path() -> str:
    return os.path.join(data_home(), "icons", "hicolor", "scalable", "apps", f"{APP_ID}.svg")


def appimage_path() -> str | None:
    """The AppImage file this process was started from, if any."""
    path = os.environ.get("APPIMAGE")
    return path if path and os.path.isfile(path) else None


def _quote(path: str) -> str:
    return '"' + path.replace("\\\\", "\\\\\\\\").replace('"', '\\\\"') + '"' if " " in path or '"' in path else path


def entry_text(exec_path: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        f"Name={LAUNCHER_NAME}",
        f"GenericName={LAUNCHER_NAME}",
        f"Comment={COMMENT}",
        f"Exec={_quote(exec_path)}",
        f"TryExec={exec_path}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=Settings;HardwareSettings;",
        f"Keywords={';'.join(KEYWORDS)};",
        f"StartupWMClass={APP_ID}",
        "",
    ])


def install(exec_path: str) -> bool:
    """Write or update the entry and icon. Returns True if anything changed."""
    changed = False
    text = entry_text(exec_path)
    path = entry_path()
    try:
        with open(path, encoding="utf-8") as f:
            current = f.read()
    except OSError:
        current = None
    if current != text:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        changed = True
    icon = icon_path()
    try:
        with open(icon, "rb") as a, open(ICON_SOURCE, "rb") as b:
            same = a.read() == b.read()
    except OSError:
        same = False
    if not same:
        os.makedirs(os.path.dirname(icon), exist_ok=True)
        shutil.copyfile(ICON_SOURCE, icon)
        changed = True
    return changed


def remove() -> None:
    for path in (entry_path(), icon_path()):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def installed() -> bool:
    return os.path.exists(entry_path())
