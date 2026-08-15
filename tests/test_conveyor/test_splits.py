"""Tests for the split assignment of record and its provenance.

Mirrors ``src/molhub/conveyor/splits.py``. Every test runs offline over a
miniature split directory written into ``tmp_path`` by
:func:`tests.test_conveyor.conftest.write_derived_splits`, whose
``metadata.json`` carries digests the fixture itself computed — so a tampered
table is a genuine disagreement between a file and its own producer's record,
not a hand-written constant that happens to be wrong.

Two constructor shapes the spec leaves implicit are assumed here, because a
test cannot call one without picking them:

* ``SplitProvenance.output_sha256`` is a mapping from filename to
  :class:`~molhub.sources.digest.Digest`, mirroring ``Artifact.digest`` — the
  repo has one type for "an algorithm plus a hex string" and this is it.
* A missing ``metadata.json`` raises :class:`SplitProvenanceMismatch`, the one
  typed error the spec's file list gives this module. What is gated is that an
  unverifiable directory is *never* loaded unverified; the type is the only
  candidate on offer.

The table is imported by its private name. ``hf-facade-03-builder-info``'s D9
made it ``_SplitTable``: the loader and the prepare stage are its two callers
and both live inside the package boundary, so the export was dropped rather
than a second table growing beside it. These are white-box unit tests of the
conveyor, which is the case ac-006 exempts — every assertion and every golden
below is unchanged from before the rename.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import molhub
import molhub.conveyor
import molhub.conveyor.splits
from molhub.conveyor.splits import SplitProvenanceMismatch, _SplitTable
from molhub.sources.digest import Digest

from .conftest import (
    IDENTITY_FILENAME,
    SPLIT_COORDINATE,
    SPLIT_COUNTS,
    SPLIT_FILENAMES,
    SPLIT_GENERATOR,
    SPLIT_RATIOS,
    SPLIT_SEED,
    write_derived_splits,
)

#: Every module of the shipped package, minus the two the table belongs to.
#: ``loader`` reads it because a table-backed split is what it counts with;
#: ``conveyor`` owns it. A third importer would be the export coming back under
#: a private name.
_PACKAGE_ROOT = Path(molhub.__file__).parent
_OWNING_SUBPACKAGES = ("loader", "conveyor")
_OUTSIDE_PRODUCTION_FILES = sorted(
    path
    for path in _PACKAGE_ROOT.rglob("*.py")
    if not any(part in _OWNING_SUBPACKAGES for part in path.relative_to(_PACKAGE_ROOT).parts)
)


def _imported_names(path: Path) -> set[str]:
    """Every name *path* binds through an import, at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _recorded_digests(root: Path) -> dict[str, str]:
    """The ``output_sha256`` block the fixture wrote, read back as hex."""
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    digests = metadata["output_sha256"]
    assert isinstance(digests, dict)
    return {str(name): str(hexdigest) for name, hexdigest in digests.items()}


class TestSplitTable:
    """One source's table per instance, trusted only after its producer agrees."""

    def test_from_derived_reads_the_named_source_table(self, splits_root):
        table = _SplitTable.from_derived(splits_root, source="mbis")
        assert table.split_of("mbis-a") == "train"
        assert table.split_of("mbis-b") == "val"
        assert table.split_of("mbis-c") == "test"

    @pytest.mark.parametrize(
        ("source", "uuid"),
        [("hessian", "hess-a"), ("mbis", "mbis-a"), ("torsion-scan", "scan-a")],
    )
    def test_each_known_source_resolves_its_own_filename(self, splits_root, source, uuid):
        """``torsion-scan`` omits ``_uuid_``; a glob would paper over exactly that."""
        assert _SplitTable.from_derived(splits_root, source=source).split_of(uuid) == "train"

    def test_a_source_reads_no_other_sources_rows(self, splits_root):
        """One table per instance: the whole set is millions of rows."""
        with pytest.raises(KeyError):
            _SplitTable.from_derived(splits_root, source="mbis").split_of("scan-a")

    def test_counts_are_per_split(self, splits_root):
        assert dict(_SplitTable.from_derived(splits_root, source="mbis").counts()) == dict(
            SPLIT_COUNTS
        )

    def test_an_unknown_source_names_the_known_ones(self, splits_root):
        with pytest.raises(KeyError) as raised:
            _SplitTable.from_derived(splits_root, source="dipole")
        message = str(raised.value)
        assert all(known in message for known in SPLIT_FILENAMES)

    def test_provenance_fields_come_from_metadata_verbatim(self, splits_root):
        provenance = _SplitTable.from_derived(splits_root, source="mbis").provenance
        assert provenance.coordinate == SPLIT_COORDINATE
        assert provenance.seed == SPLIT_SEED
        assert provenance.ratios == SPLIT_RATIOS
        assert provenance.generator == SPLIT_GENERATOR

    def test_provenance_carries_the_digest_of_the_file_it_verified(self, splits_root):
        provenance = _SplitTable.from_derived(splits_root, source="mbis").provenance
        recorded = _recorded_digests(splits_root)["mbis_uuid_splits.csv.gz"]
        assert provenance.output_sha256["mbis_uuid_splits.csv.gz"] == Digest.sha256(recorded)

    def test_a_tampered_table_is_refused_naming_the_file(self, splits_root):
        """Verification precedes parsing, so unreadable bytes still name the file."""
        (splits_root / "mbis_uuid_splits.csv.gz").write_bytes(b"not the bytes that were hashed")
        with pytest.raises(SplitProvenanceMismatch) as raised:
            _SplitTable.from_derived(splits_root, source="mbis")
        assert "mbis_uuid_splits.csv.gz" in str(raised.value)

    def test_a_missing_metadata_file_is_refused(self, splits_root):
        (splits_root / "metadata.json").unlink()
        with pytest.raises(SplitProvenanceMismatch) as raised:
            _SplitTable.from_derived(splits_root, source="mbis")
        assert "metadata.json" in str(raised.value)

    def test_an_unknown_uuid_raises_without_listing_the_table(self, splits_root):
        table = _SplitTable.from_derived(splits_root, source="mbis")
        with pytest.raises(KeyError) as raised:
            table.split_of("mbis-absent")
        message = str(raised.value)
        assert "mbis-absent" in message
        assert "mbis-b" not in message

    def test_from_identity_is_keyed_by_identity(self, splits_root):
        table = _SplitTable.from_identity(splits_root)
        assert table.split_of("identity-1") == "train"
        assert table.split_of("identity-2") == "val"
        assert table.split_of("identity-3") == "test"

    def test_from_identity_holds_no_uuids(self, splits_root):
        """The two key spaces stay honest about which one an instance holds."""
        with pytest.raises(KeyError):
            _SplitTable.from_identity(splits_root).split_of("mbis-a")

    def test_from_identity_counts_are_per_split(self, splits_root):
        assert dict(_SplitTable.from_identity(splits_root).counts()) == dict(SPLIT_COUNTS)

    def test_from_identity_surfaces_the_same_provenance_fields(self, splits_root):
        provenance = _SplitTable.from_identity(splits_root).provenance
        assert provenance.coordinate == SPLIT_COORDINATE
        assert provenance.seed == SPLIT_SEED
        assert provenance.ratios == SPLIT_RATIOS
        assert provenance.generator == SPLIT_GENERATOR

    def test_from_identity_refuses_a_tampered_table(self, splits_root):
        """One implementation, one provenance check — not one checked path of two."""
        (splits_root / IDENTITY_FILENAME).write_bytes(b"not the bytes that were hashed")
        with pytest.raises(SplitProvenanceMismatch) as raised:
            _SplitTable.from_identity(splits_root)
        assert IDENTITY_FILENAME in str(raised.value)

    def test_from_identity_refuses_a_missing_metadata_file(self, tmp_path):
        root = write_derived_splits(tmp_path / "splits")
        (root / "metadata.json").unlink()
        with pytest.raises(SplitProvenanceMismatch) as raised:
            _SplitTable.from_identity(root)
        assert "metadata.json" in str(raised.value)


class TestSplitTableIsInternal:
    """ac-006 / D9: the export goes, the implementation stays exactly as it was.

    ``SplitTable`` was public because ``-02-roster`` had no other way to hand a
    caller a verified table. The loader is the second caller, and it lives in
    the same distribution, so the name is now package-internal: one table
    implementation, two callers, and no promise to anyone outside that the type
    is theirs to construct.
    """

    def test_the_module_defines_the_private_name(self):
        assert isinstance(getattr(molhub.conveyor.splits, "_SplitTable", None), type)

    def test_the_module_declares_it_nowhere_in_its_own_exports(self):
        assert "SplitTable" not in molhub.conveyor.splits.__all__
        assert "_SplitTable" not in molhub.conveyor.splits.__all__

    def test_the_package_no_longer_exports_it(self):
        assert "SplitTable" not in molhub.conveyor.__all__

    def test_the_package_keeps_no_public_alias_of_it(self):
        """An ``__all__`` edit alone would leave ``from molhub.conveyor import`` working."""
        assert not hasattr(molhub.conveyor, "SplitTable")

    def test_the_two_alternate_constructors_are_unchanged(self):
        """D9 moves the export and nothing else; these are the same two verbs."""
        assert hasattr(_SplitTable, "from_derived")
        assert hasattr(_SplitTable, "from_identity")

    def test_there_are_production_modules_to_scan(self):
        assert _OUTSIDE_PRODUCTION_FILES, f"no modules found under {_PACKAGE_ROOT}"

    @pytest.mark.parametrize(
        "module_file",
        _OUTSIDE_PRODUCTION_FILES,
        ids=lambda p: f"{p.parent.name}/{p.name}",
    )
    def test_no_production_module_outside_the_two_owners_imports_it(self, module_file):
        offenders = _imported_names(module_file) & {"SplitTable", "_SplitTable"}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"
