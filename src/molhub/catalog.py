"""Built-in artifact catalog.

Python modules are the source of truth. Each dataset file declares a
``MANIFEST`` or ``MANIFESTS``; this module collects them. The frontend and any other
non-Python client asks the package for a snapshot — the project ships
no YAML registry.
"""

from __future__ import annotations

from molhub.manifest import Manifest

__all__ = ["builtin_manifests"]


def builtin_manifests() -> tuple[Manifest, ...]:
    """Every downloadable artifact the package declares, in a stable order."""
    from molhub.dataset.liqwat import MANIFEST as liqwat
    from molhub.dataset.omol25 import MANIFEST as omol25
    from molhub.dataset.phalkethoh_mm import MANIFEST as phalkethoh
    from molhub.dataset.polymer_tg import MANIFESTS as polymer_tg
    from molhub.dataset.qm9 import MANIFEST as qm9
    from molhub.dataset.revmd17 import MANIFEST as revmd17
    from molhub.dataset.themol_files import MANIFESTS as themol
    from molhub.dataset.threebpa import MANIFEST as threebpa
    from molhub.dataset.zinc_typing import MANIFEST as zinc

    return (qm9, revmd17, threebpa, *polymer_tg, phalkethoh, zinc, omol25, liqwat, *themol)
