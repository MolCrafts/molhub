"""Shared test doubles for the dataset test package.

Import by package path (``from tests.test_dataset.conftest import FakeHub``);
test modules must not carry their own copies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType


@dataclass
class FakeHub:
    """An :class:`~molhub.dataset.hub.ArtifactHub` serving files already on disk.

    Records what it was asked for, so a download path can be exercised with no
    registry, no driver, and no network — and a test can assert the dataset
    requests one pinned coordinate and only the roles it actually needs.
    """

    paths: dict[str, Path] = field(default_factory=dict)
    calls: list[tuple[str, list[str] | None]] = field(default_factory=list)

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        self.calls.append((coordinate, roles))
        wanted = list(self.paths) if roles is None else roles
        return {role: self.paths[role] for role in wanted}


#: The wrapper identifiers ``hf-facade-01-meta-dissolution`` deletes. Boundary
#: aware on purpose: ``write_metadata`` (DerivedLayout's unrelated conveyor API)
#: and ``TargetSchema`` / ``TargetDeclaration`` must never match.
DISSOLVED_WRAPPERS = re.compile(r"\bTargets\b|\bMetaCodec\b|\bwrite_meta\b(?!data)")


def dissolved_wrapper_names(module: ModuleType) -> list[str]:
    """Deleted meta-wrapper identifiers still named in *module*'s source."""
    path = module.__file__
    assert path is not None
    source = Path(path).read_text(encoding="utf-8")
    return sorted({match.group() for match in DISSOLVED_WRAPPERS.finditer(source)})


def rows_of(dataset, table: str):
    """The per-row lengths ``molix.data.BaseDataset.nrows_of`` would read.

    molhub does not depend on molnex, so that routing is mirrored here rather
    than imported: a declared ``counted_tables`` column first, the measuring
    ``count_rows`` verb second. A test asserting on the result is asserting
    that this container meets the protocol — not that it has some method.
    """
    import numpy as np

    declared = getattr(type(dataset), "counted_tables", None) or {}
    if table in declared:
        return np.asarray(getattr(dataset, declared[table]))
    return np.asarray(dataset.count_rows(table))
