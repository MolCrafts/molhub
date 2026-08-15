"""The two refusals a caller of this layer has to be able to name.

Both are things a script legitimately catches — one to build the derivation, the
other to print the split names it should have asked for — so both are exported
from :mod:`molhub.loader` and from the package root beside ``load_dataset``
itself. An exception reachable only through a private module is one callers catch
as ``Exception``, which catches everything else too.

**Why the absent split table is not a provenance mismatch.**
``$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1/`` is derived, never
downloaded, and a reader who has never built it is in the ordinary first-run
state: nothing mismatches, because nothing was ever written.
:class:`~molhub.conveyor.splits.SplitProvenanceMismatch` means the opposite —
the record exists and the bytes moved under it — and answering both with one
type would make "run the generator" and "your table changed after it was
written" the same sentence. So the absent case gets its own type here, in the
layer whose callers act on it, and the mismatch stays exactly where it was.

Reference:
    ``.claude/specs/hf-facade-03-builder-info.md`` § D6; the 2026-08-15 operator
    override recorded in ``.claude/notes/notes.md``
    (``mol:note:topic:hf-style-api``).
"""

from __future__ import annotations

__all__ = ["SplitTableUnavailable", "UnknownSplit"]


class SplitTableUnavailable(Exception):
    """The published split derivation is not on this machine.

    Nothing downloads it: ``class1-universal-splits@1`` is *built*, by the
    generator molhub ships at ``molhub.scripts.build_class1_splits``. The message
    therefore names the dataset that was asked for, the derivation that is
    missing, the path that was looked at, the command that writes it and what
    that command reads — a refusal a reader cannot act on is a wall.

    Deliberately **not** a subclass of
    :class:`~molhub.conveyor.splits.SplitProvenanceMismatch`: see this module's
    docstring for why the two states are answered separately.
    """


class UnknownSplit(KeyError):
    """The split name is not one this dataset declares.

    A :class:`KeyError`, because that is what ``load_dataset`` has always
    documented and callers already catch; the type only narrows it, so a caller
    who wants to distinguish "no such split" from any other key miss can.

    ``KeyError.__str__`` is ``repr(args[0])``, which renders a sentence with the
    quotes baked in and reads like a broken dict lookup. This refusal *is* a
    sentence — it lists the declared names — so it renders itself.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self._message = message

    def __str__(self) -> str:
        return self._message
