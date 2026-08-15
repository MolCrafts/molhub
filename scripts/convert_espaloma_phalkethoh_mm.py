#!/usr/bin/env python3
"""Deprecated location — the espaloma conversion ships inside the wheel now.

``dataset:espaloma/phalkethoh-mm-small@1`` publishes bytes its own dataset class
cannot read, and the loader's refusal hands the reader one command to fix that.
A command that only exists in a git checkout is not one a pip-installed reader
can run, so the implementation moved to
``src/molhub/scripts/convert_espaloma_phalkethoh_mm.py`` and is run as::

    python -m molhub.scripts.convert_espaloma_phalkethoh_mm --src <zip> --out <dir>

This file keeps working because it is in every runbook, and it delegates rather
than duplicating: two producers of one converted tree drift, and nothing detects
it — the dataset reads whichever one wrote the directory it was pointed at.
"""

from __future__ import annotations

import sys

from molhub.scripts.convert_espaloma_phalkethoh_mm import main

if __name__ == "__main__":
    sys.exit(main())
