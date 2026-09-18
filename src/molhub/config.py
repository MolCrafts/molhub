"""Process-wide molhub configuration.

One field, ``home_dir``: the cache root as a :class:`~pathlib.Path`. Assignment
is ``config.home_dir = path``. There is no ``home`` key and no ``writable`` key.

The initial value is ``$MOLHUB_HOME`` when that variable is set and non-empty,
otherwise ``Path.home() / ".cache" / "molhub"``.

**Why the environment variable is read here.** Everything molhub caches lives
under ``home_dir`` — a download, an extracted tarball, a count sidecar — so on a
cluster it has to be steerable from outside the process, by a job script that
knows which filesystem has room. ``$MOLHUB_HOME`` was already the name used for
that: it is referenced in :mod:`molhub.coordinate` and
:mod:`molhub.conveyor.roster`, and job scripts set it. It was **not** read
anywhere, so setting it did nothing, and a launcher helper whose whole purpose
was "keep the 4m extract off the 30 GiB home quota" by setting it had no effect
at all: the OMol25 4m tarball (19 GiB) re-downloaded to ``~/.cache/molhub`` and
filled ``/home`` to 100 %, at which point the extraction died with
``OSError: [Errno 122] Disk quota exceeded`` (2026-09-18). Reading it here is
what makes the name mean what every caller already assumed it meant.

Read **once, at import**. A process that wants to change the root afterwards
assigns to ``config.home_dir``, which is the documented knob and what the CLI's
``--home`` does; re-reading the environment on every access would make the two
disagree.

Callers write ``from molhub.config import config``. This module is not
re-exported from :mod:`molhub`.
"""

from __future__ import annotations

import os
from pathlib import Path

from molcfg import Config


def _initial_home_dir() -> Path:
    """``$MOLHUB_HOME`` if set and non-empty, else ``~/.cache/molhub``.

    An empty or whitespace-only value is treated as unset rather than as the
    current directory: ``MOLHUB_HOME=`` in a job script is how a variable that
    was never assigned looks, and resolving that to ``Path("")`` would put the
    cache wherever the process happened to start.
    """
    raw = (os.environ.get("MOLHUB_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "molhub"


class MolhubConfig(Config):
    """Named :class:`molcfg.Config` root for molhub.

    Subclasses :class:`molcfg.Config` because that type uses ``__slots__``, so
    the project type is the subclass. No extra methods: molhub has no precision
    contract. Nested children remain plain :class:`Config`.

    The singleton's one field is ``home_dir`` (a :class:`~pathlib.Path`, a
    directory, not a physical unit).
    """

    __slots__ = ()


config = MolhubConfig(
    {
        "home_dir": _initial_home_dir(),
    }
)
