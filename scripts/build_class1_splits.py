#!/usr/bin/env python3
"""Deprecated location — the generator ships inside the wheel now.

``<home>/derived/molcrafts/class1-universal-splits/1/`` is the split
assignment every THEMol split view and every prepared block is routed by, and
nobody publishes it: it is derived, on the machine that wants it. A generator
that lived only here would mean a pip-installed molhub could not open a single
THEMol split until its user had cloned the repository to reach a file that never
shipped — so the implementation moved to
``src/molhub/scripts/build_class1_splits.py`` and is run as::

    python -m molhub.scripts.build_class1_splits [--fetch] [--seed 20260814]

This file keeps working because it is in every runbook, and it delegates rather
than duplicating: two producers of one derivation drift, and nothing detects it,
because the published tables verify against whichever copy's ``metadata.json``
was written beside them.
"""

from __future__ import annotations

import sys

from molhub.scripts.build_class1_splits import main

if __name__ == "__main__":
    sys.exit(main())
