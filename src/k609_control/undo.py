"""Undo: what a change replaced, and how to put it back.

Each change made from the app records a Snapshot of the parts it is about to change, taken from the
app's copy of the keyboard's state. Undoing writes those parts back with the same checked writes
the app always uses. Kept in memory for the session.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from . import keymap, lighting, macros, profiles, selfdefine

LIMIT = 30


@dataclass
class Snapshot:
    description: str
    light: tuple[lighting.State, str] | None = None        # effect and levels, Fixed on colour "rrggbb" or ""
    keys: dict[str, int] | None = None                      # key name -> code, before the change
    macros: list[macros.Macro] | None = None                 # macro list (with key assignments)
    selfdef: tuple[dict, int] | None = None                  # Self define colours and brightness as last sent
    profile_file: profiles.Profile | None = None             # profile to write back (it was changed or deleted)
    profile_created: str | None = None                       # profile to delete (it was created)

    @property
    def needs_keyboard(self) -> bool:
        return any(x is not None for x in (self.light, self.keys, self.macros, self.selfdef))


def copy_macros(ms) -> list[macros.Macro]:
    return copy.deepcopy(list(ms))


def restore(devnode: str, snap: Snapshot, **io) -> None:
    """Write the snapshot's keyboard parts back: keys, then macros, Self define and lighting last."""
    if snap.keys is not None:
        changes = {name: code for name, code in snap.keys.items()
                   if code < keymap.MACRO_CODE and code in keymap.TARGETS}
        keymap.remap(devnode, changes, **io)
    if snap.macros is not None:
        macros.apply(devnode, snap.macros, **io)
    if snap.selfdef is not None:
        colours, brightness = snap.selfdef
        selfdefine.apply(devnode, colours, brightness, **io)
    if snap.light is not None:
        st, colour = snap.light
        rgb = tuple(bytes.fromhex(colour)) if colour else None
        lighting.apply(devnode, effect=st.effect, levels=st.levels, colour=rgb, **io)


def restore_files(snap: Snapshot, folder: str | None = None) -> None:
    if snap.profile_file is not None:
        profiles.save(snap.profile_file, folder)
    if snap.profile_created is not None:
        try:
            profiles.delete(snap.profile_created, folder)
        except FileNotFoundError:
            pass
