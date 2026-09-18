"""Runnable derivations that ship **inside** the wheel.

Some artifacts molhub reads are not published by anyone: they are *derived*, on
the machine that wants them. ``class1-universal-splits@1`` is the one that
matters today — every THEMol split view and every prepared block is routed by
it, and it lives under ``<home>/derived/`` because no platform serves it.

A derivation the product requires is part of the product. A generator that lived
only in the repository checkout would mean a pip-installed molhub could not open
a single THEMol split until its user had cloned a file that never shipped, so
the generators live here and are run as modules::

    python -m molhub.scripts.build_class1_splits

Each module in this package exposes exactly one ``main(argv=None, ...) -> int``
and its collaborators as types. They are entry points, not a public API: nothing
under :mod:`molhub.loader`, :mod:`molhub.dataset` or :mod:`molhub.conveyor`
imports them, and the refusals that *name* them do so as a command a reader can
type rather than as a symbol to import.
"""
