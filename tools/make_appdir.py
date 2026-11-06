#!/usr/bin/env python3
"""Assemble a self-contained AppDir: the app, Python, PyGObject, GTK 4 and their libraries.

Runs on a Debian/Ubuntu build system (Ubuntu 22.04 for releases, so the AppImage works on distros
from about 2022 on). Libraries listed in tools/excludelist (glibc, GPU drivers, X11/Wayland
client libraries, fontconfig, ...) are left out: they must come from the host.

Usage: make_appdir.py APPDIR
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import sysconfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCH_LIB = "/usr/lib/x86_64-linux-gnu"
PY = f"python{sys.version_info.major}.{sys.version_info.minor}"
APP_ID = "io.github.HypestHyper.K609KeyboardControl"

# Libraries GObject introspection opens by name from the typelibs, so ldd can't find them.
TYPELIB_LIBS = [
    "libgtk-4.so.1", "libgraphene-1.0.so.0", "libpango-1.0.so.0", "libpangocairo-1.0.so.0",
    "libpangoft2-1.0.so.0", "libgdk_pixbuf-2.0.so.0", "libcairo.so.2", "libcairo-gobject.so.2",
    "libgirepository-1.0.so.1", "libgio-2.0.so.0", "libgobject-2.0.so.0", "libglib-2.0.so.0",
    "libgmodule-2.0.so.0",
]
TYPELIBS = ["GLib-2.0", "GObject-2.0", "Gio-2.0", "GModule-2.0", "Gtk-4.0", "Gdk-4.0", "Gsk-4.0",
            "Graphene-1.0", "Pango-1.0", "PangoCairo-1.0", "cairo-1.0", "HarfBuzz-0.0", "GdkPixbuf-2.0",
            "freetype2-2.0", "GdkX11-4.0", "GdkWayland-4.0", "PangoFT2-1.0", "fontconfig-2.0", "xlib-2.0",
            "Gst-1.0", "GstBase-1.0"]
STDLIB_SKIP = {"test", "idlelib", "tkinter", "turtledemo", "lib2to3", "ensurepip", "pydoc_data",
               "distutils", "unittest", "__pycache__", "site-packages", "dist-packages", "config-" + PY}


def excluded() -> set[str]:
    names = set()
    with open(os.path.join(ROOT, "tools", "excludelist"), encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if line:
                names.add(line.split()[0])
    return names


def is_elf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False


def needed(path: str) -> dict[str, str]:
    """soname -> resolved path, from ldd."""
    out = subprocess.run(["ldd", path], capture_output=True, text=True).stdout
    deps = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\S+) => (\S+) \(", line)
        if m and os.path.exists(m.group(2)):
            deps[m.group(1)] = m.group(2)
    return deps


def copy(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst, follow_symlinks=True)


def main(appdir: str) -> None:
    usr = os.path.join(appdir, "usr")
    libdir = os.path.join(usr, "lib")
    skip = excluded()

    # 1. Python interpreter and standard library
    copy(os.path.realpath(sys.executable), os.path.join(usr, "bin", PY))
    os.symlink(PY, os.path.join(usr, "bin", "python3"))
    stdlib = sysconfig.get_paths()["stdlib"]
    dest_stdlib = os.path.join(libdir, PY)
    shutil.copytree(stdlib, dest_stdlib, symlinks=False,
                    ignore=lambda d, names: [n for n in names if n in STDLIB_SKIP or n.endswith(".pyc")])

    # 2. PyGObject (Debian keeps it in dist-packages)
    gi_src = os.path.dirname(__import__("gi").__file__)
    shutil.copytree(gi_src, os.path.join(libdir, "python3", "dist-packages", "gi"),
                    ignore=shutil.ignore_patterns("__pycache__"))

    # 3. The app
    shutil.copytree(os.path.join(ROOT, "src", "k609_control"), os.path.join(libdir, "k609-keyboard-control", "k609_control"),
                    ignore=shutil.ignore_patterns("__pycache__"))

    # 4. Typelibs
    for name in TYPELIBS:
        src = os.path.join(ARCH_LIB, "girepository-1.0", f"{name}.typelib")
        if os.path.exists(src):
            copy(src, os.path.join(libdir, "girepository-1.0", f"{name}.typelib"))

    # 5. gdk-pixbuf loaders (SVG icons), with a cache rewritten at start-up by AppRun
    loaders = glob.glob(os.path.join(ARCH_LIB, "gdk-pixbuf-2.0", "2.10.0", "loaders", "*.so"))
    for so in loaders:
        copy(so, os.path.join(libdir, "gdk-pixbuf", "loaders", os.path.basename(so)))
    query = shutil.which("gdk-pixbuf-query-loaders") or os.path.join(ARCH_LIB, "gdk-pixbuf-2.0", "gdk-pixbuf-query-loaders")
    cache = subprocess.run([query] + sorted(glob.glob(os.path.join(libdir, "gdk-pixbuf", "loaders", "*.so"))),
                           capture_output=True, text=True, check=True).stdout
    with open(os.path.join(libdir, "gdk-pixbuf", "loaders.cache.in"), "w", encoding="utf-8") as f:
        f.write(cache.replace(os.path.abspath(appdir), "@APPDIR@"))

    # 6. GSettings schemas GTK needs, and the symbolic icons the app uses
    schemas = os.path.join(usr, "share", "glib-2.0", "schemas")
    for xml in glob.glob("/usr/share/glib-2.0/schemas/org.gtk.gtk4.*.xml"):
        copy(xml, os.path.join(schemas, os.path.basename(xml)))
    subprocess.run(["glib-compile-schemas", schemas], check=True)
    # Adwaita's symbolic icons (the app's icons) and hicolor's index, as fallback for hosts without them
    for theme in ("Adwaita", "hicolor"):
        src = os.path.join("/usr/share/icons", theme)
        if not os.path.isfile(os.path.join(src, "index.theme")):
            continue
        dst = os.path.join(usr, "share", "icons", theme)
        copy(os.path.join(src, "index.theme"), os.path.join(dst, "index.theme"))
        if theme == "Adwaita":
            for sub in ("symbolic", "scalable"):
                if os.path.isdir(os.path.join(src, sub)):
                    shutil.copytree(os.path.join(src, sub), os.path.join(dst, sub), dirs_exist_ok=True)

    # 7. Shared libraries: everything linked, minus the excludelist, until nothing new turns up
    for soname in TYPELIB_LIBS:
        copy(os.path.join(ARCH_LIB, soname), os.path.join(libdir, soname))
    seen = set()
    while True:
        elfs = [p for p in glob.glob(os.path.join(usr, "**", "*"), recursive=True)
                if os.path.isfile(p) and not os.path.islink(p) and is_elf(p) and p not in seen]
        if not elfs:
            break
        for elf in elfs:
            seen.add(elf)
            for soname, path in needed(elf).items():
                if soname in skip or soname.startswith(("libnvidia", "libvulkan")):
                    continue
                dst = os.path.join(libdir, soname)
                if not os.path.exists(dst):
                    copy(path, dst)

    # 8. Byte-compile once, so the read-only AppImage starts quickly
    subprocess.run([sys.executable, "-m", "compileall", "-q", "-j", "0", libdir], check=False)

    # 9. AppRun, desktop entry, icon
    copy(os.path.join(ROOT, "packaging", "AppRun"), os.path.join(appdir, "AppRun"))
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)
    copy(os.path.join(ROOT, "packaging", f"{APP_ID}.desktop"), os.path.join(appdir, f"{APP_ID}.desktop"))
    copy(os.path.join(ROOT, "packaging", f"{APP_ID}.desktop"), os.path.join(usr, "share", "applications", f"{APP_ID}.desktop"))
    icon = os.path.join(ROOT, "src", "k609_control", "resources", f"{APP_ID}.svg")
    copy(icon, os.path.join(appdir, "k609-keyboard-control.svg"))
    copy(icon, os.path.join(usr, "share", "icons", "hicolor", "scalable", "apps", f"{APP_ID}.svg"))
    print(f"AppDir ready: {appdir}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(os.path.abspath(sys.argv[1]))
