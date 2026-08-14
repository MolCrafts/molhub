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
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from molhub.conveyor.splits import SplitProvenanceMismatch, SplitTable
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


def _recorded_digests(root: Path) -> dict[str, str]:
    """The ``output_sha256`` block the fixture wrote, read back as hex."""
    metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    digests = metadata["output_sha256"]
    assert isinstance(digests, dict)
    return {str(name): str(hexdigest) for name, hexdigest in digests.items()}


class TestSplitTable:
    """One source's table per instance, trusted only after its producer agrees."""

    def test_from_derived_reads_the_named_source_table(self, splits_root):
        table = SplitTable.from_derived(splits_root, source="mbis")
        assert table.split_of("mbis-a") == "train"
        assert table.split_of("mbis-b") == "val"
        assert table.split_of("mbis-c") == "test"

    @pytest.mark.parametrize(
        ("source", "uuid"),
        [("hessian", "hess-a"), ("mbis", "mbis-a"), ("torsion-scan", "scan-a")],
    )
    def test_each_known_source_resolves_its_own_filename(self, splits_root, source, uuid):
        """``torsion-scan`` omits ``_uuid_``; a glob would paper over exactly that."""
        assert SplitTable.from_derived(splits_root, source=source).split_of(uuid) == "train"

    def test_a_source_reads_no_other_sources_rows(self, splits_root):
        """One table per instance: the whole set is millions of rows."""
        with pytest.raises(KeyError):
            SplitTable.from_derived(splits_root, source="mbis").split_of("scan-a")

    def test_counts_are_per_split(self, splits_root):
        assert dict(SplitTable.from_derived(splits_root, source="mbis").counts()) == dict(
            SPLIT_COUNTS
        )

    def test_an_unknown_source_names_the_known_ones(self, splits_root):
        with pytest.raises(KeyError) as raised:
            SplitTable.from_derived(splits_root, source="dipole")
        message = str(raised.value)
        assert all(known in message for known in SPLIT_FILENAMES)

    def test_provenance_fields_come_from_metadata_verbatim(self, splits_root):
        provenance = SplitTable.from_derived(splits_root, source="mbis").provenance
        assert provenance.coordinate == SPLIT_COORDINATE
        assert provenance.seed == SPLIT_SEED
        assert provenance.ratios == SPLIT_RATIOS
        assert provenance.generator == SPLIT_GENERATOR

    def test_provenance_carries_the_digest_of_the_file_it_verified(self, splits_root):
        provenance = SplitTable.from_derived(splits_root, source="mbis").provenance
        recorded = _recorded_digests(splits_root)["mbis_uuid_splits.csv.gz"]
        assert provenance.output_sha256["mbis_uuid_splits.csv.gz"] == Digest.sha256(recorded)

    def test_a_tampered_table_is_refused_naming_the_file(self, splits_root):
        """Verification precedes parsing, so unreadable bytes still name the file."""
        (splits_root / "mbis_uuid_splits.csv.gz").write_bytes(b"not the bytes that were hashed")
        with pytest.raises(SplitProvenanceMismatch) as raised:
            SplitTable.from_derived(splits_root, source="mbis")
        assert "mbis_uuid_splits.csv.gz" in str(raised.value)

    def test_a_missing_metadata_file_is_refused(self, splits_root):
        (splits_root / "metadata.json").unlink()
        with pytest.raises(SplitProvenanceMismatch) as raised:
            SplitTable.from_derived(splits_root, source="mbis")
        assert "metadata.json" in str(raised.value)

    def test_an_unknown_uuid_raises_without_listing_the_table(self, splits_root):
        table = SplitTable.from_derived(splits_root, source="mbis")
        with pytest.raises(KeyError) as raised:
            table.split_of("mbis-absent")
        message = str(raised.value)
        assert "mbis-absent" in message
        assert "mbis-b" not in message

    def test_from_identity_is_keyed_by_identity(self, splits_root):
        table = SplitTable.from_identity(splits_root)
        assert table.split_of("identity-1") == "train"
        assert table.split_of("identity-2") == "val"
        assert table.split_of("identity-3") == "test"

    def test_from_identity_holds_no_uuids(self, splits_root):
        """The two key spaces stay honest about which one an instance holds."""
        with pytest.raises(KeyError):
            SplitTable.from_identity(splits_root).split_of("mbis-a")

    def test_from_identity_counts_are_per_split(self, splits_root):
        assert dict(SplitTable.from_identity(splits_root).counts()) == dict(SPLIT_COUNTS)

    def test_from_identity_surfaces_the_same_provenance_fields(self, splits_root):
        provenance = SplitTable.from_identity(splits_root).provenance
        assert provenance.coordinate == SPLIT_COORDINATE
        assert provenance.seed == SPLIT_SEED
        assert provenance.ratios == SPLIT_RATIOS
        assert provenance.generator == SPLIT_GENERATOR

    def test_from_identity_refuses_a_tampered_table(self, splits_root):
        """One implementation, one provenance check — not one checked path of two."""
        (splits_root / IDENTITY_FILENAME).write_bytes(b"not the bytes that were hashed")
        with pytest.raises(SplitProvenanceMismatch) as raised:
            SplitTable.from_identity(splits_root)
        assert IDENTITY_FILENAME in str(raised.value)

    def test_from_identity_refuses_a_missing_metadata_file(self, tmp_path):
        root = write_derived_splits(tmp_path / "splits")
        (root / "metadata.json").unlink()
        with pytest.raises(SplitProvenanceMismatch) as raised:
            SplitTable.from_identity(root)
        assert "metadata.json" in str(raised.value)
