"""Tests for the REMOTE-tier block roster.

Mirrors ``src/molhub/conveyor/roster.py``. The roster is a *projection* of a
manifest, so almost every test here is a statement about something the roster
did **not** do: it did not re-derive a digest, did not copy a unit onto a
block, did not invent a split, and did not quietly admit a block the byte
budget or the verification step cannot cover.

The fixture manifest lists its roles as ``index``, ``shard-001``,
``shard-000`` — deliberately not in sorted order, so "manifest role order" is
distinguishable from "sorted order".
"""

from __future__ import annotations

import dataclasses

import pytest

from molhub.conveyor.block import BlockId
from molhub.conveyor.roster import (
    BlockRoster,
    NoShardArtifacts,
    RemoteBlock,
    RoleSourceMismatch,
    RosterError,
    UnsizedBlock,
    UnverifiableBlock,
)
from molhub.conveyor.splits import _SplitTable
from molhub.manifest import Manifest

from .conftest import (
    COORDINATE,
    INDEX_ARTIFACT,
    ROLE_NAME,
    SHARD_0_ARTIFACT,
    SHARD_0_SIZE,
    SHARD_1_SIZE,
    UNSIZED_SHARD_ARTIFACT,
    UNVERIFIABLE_SHARD_ARTIFACT,
    manifest_yaml,
)

SHARD_0 = BlockId(COORDINATE, ROLE_NAME, None, "shard-000")
SHARD_1 = BlockId(COORDINATE, ROLE_NAME, None, "shard-001")


class TestRemoteBlock:
    """Five fields, carried verbatim, and nothing that belongs to the role."""

    def test_it_declares_exactly_the_five_projected_fields(self):
        assert tuple(field.name for field in dataclasses.fields(RemoteBlock)) == (
            "id",
            "filename",
            "size",
            "digest",
            "locators",
        )

    def test_it_is_frozen(self, manifest, role):
        block = BlockRoster(manifest, role).block(SHARD_0)
        with pytest.raises(dataclasses.FrozenInstanceError):
            block.filename = "somewhere_else.h5"

    def test_filename_is_the_artifact_filename(self, manifest, role):
        block = BlockRoster(manifest, role).block(SHARD_0)
        assert block.filename == manifest.artifact("shard-000").filename

    def test_size_is_the_artifact_size(self, manifest, role):
        block = BlockRoster(manifest, role).block(SHARD_0)
        assert block.size == manifest.artifact("shard-000").size

    def test_digest_is_the_artifacts_own_object(self, manifest, role):
        """Identity, not equality: a re-computed digest would be a new object."""
        block = BlockRoster(manifest, role).block(SHARD_0)
        assert block.digest is manifest.artifact("shard-000").digest

    def test_locators_are_the_artifacts_own_object(self, manifest, role):
        block = BlockRoster(manifest, role).block(SHARD_0)
        assert block.locators is manifest.artifact("shard-000").locators

    def test_no_role_fact_is_copied_onto_the_block(self, manifest, role):
        """Units live on the injected role; a second copy is a second place to be wrong."""
        block = BlockRoster(manifest, role).block(SHARD_0)
        for absent in ("unit", "units", "target", "targets", "sampling_unit", "reference_method"):
            assert not hasattr(block, absent)


class TestBlockRoster:
    """What the REMOTE tier holds, how big it is, and what it must hash to."""

    def test_blocks_are_in_manifest_role_order(self, manifest, role):
        roster = BlockRoster(manifest, role)
        assert tuple(block.id.block_id for block in roster.blocks()) == ("shard-001", "shard-000")

    def test_only_shard_roles_become_blocks(self, manifest, role):
        roster = BlockRoster(manifest, role)
        assert len(roster.blocks()) == 2

    def test_hot_roles_reports_the_index(self, manifest, role):
        """A 1.45 GB CSV admitted to a 40 GB rolling budget is an accounting error."""
        assert BlockRoster(manifest, role).hot_roles == ("index",)

    def test_total_bytes_sums_the_shards_only(self, manifest, role):
        assert BlockRoster(manifest, role).total_bytes() == SHARD_0_SIZE + SHARD_1_SIZE

    def test_block_round_trips_by_id(self, manifest, role):
        roster = BlockRoster(manifest, role)
        assert roster.block(SHARD_1) is roster.block(SHARD_1)
        assert roster.block(SHARD_1).id == SHARD_1

    def test_an_unknown_block_id_lists_the_available_ones(self, manifest, role):
        roster = BlockRoster(manifest, role)
        with pytest.raises(KeyError) as raised:
            roster.block(BlockId(COORDINATE, ROLE_NAME, None, "shard-404"))
        message = str(raised.value)
        assert "shard-000" in message and "shard-001" in message

    def test_the_role_is_readable_without_being_copied(self, manifest, role):
        assert BlockRoster(manifest, role).role is role

    def test_block_id_source_is_the_manifest_coordinate(self, manifest, role):
        roster = BlockRoster(manifest, role)
        assert {block.id.source for block in roster.blocks()} == {manifest.coordinate.canonical}

    def test_block_id_task_is_the_role_name(self, manifest, role):
        roster = BlockRoster(manifest, role)
        assert {block.id.task for block in roster.blocks()} == {role.name}

    def test_block_id_block_id_is_the_artifact_role(self, manifest, role):
        roster = BlockRoster(manifest, role)
        assert {block.id.block_id for block in roster.blocks()} == {"shard-000", "shard-001"}

    def test_a_published_shard_has_no_split(self, manifest, role):
        """The split table keys molecules and scans, not shard roles — so: None."""
        roster = BlockRoster(manifest, role)
        assert all(block.id.split is None for block in roster.blocks())

    def test_split_provenance_is_absent_without_a_split_table(self, manifest, role):
        assert BlockRoster(manifest, role).split_provenance is None

    def test_split_provenance_is_the_tables_own(self, manifest, role, splits_root):
        table = _SplitTable.from_derived(splits_root, source="mbis")
        roster = BlockRoster(manifest, role, splits=table)
        assert roster.split_provenance is table.provenance

    def test_an_unsized_artifact_is_refused(self, role):
        """I4 bounds bytes; a block with no declared size cannot be budgeted."""
        manifest = Manifest.from_yaml(
            manifest_yaml(artifacts=INDEX_ARTIFACT + SHARD_0_ARTIFACT + UNSIZED_SHARD_ARTIFACT)
        )
        with pytest.raises(UnsizedBlock) as raised:
            BlockRoster(manifest, role)
        assert "shard-002" in str(raised.value)

    def test_an_undigested_artifact_is_refused(self, role):
        """I6 needs something to verify against; a size is not a digest."""
        manifest = Manifest.from_yaml(
            manifest_yaml(artifacts=INDEX_ARTIFACT + SHARD_0_ARTIFACT + UNVERIFIABLE_SHARD_ARTIFACT)
        )
        with pytest.raises(UnverifiableBlock) as raised:
            BlockRoster(manifest, role)
        assert "shard-003" in str(raised.value)

    def test_a_manifest_with_no_shard_role_is_refused(self, role):
        """An empty roster would read as "nothing to fetch", which is a lie."""
        manifest = Manifest.from_yaml(manifest_yaml(artifacts=INDEX_ARTIFACT))
        with pytest.raises(NoShardArtifacts):
            BlockRoster(manifest, role)

    def test_a_role_not_declaring_this_coordinate_is_refused(self, manifest, other_role):
        """Individually well-formed, wholly wrong: mbis shards under the torsion role."""
        with pytest.raises(RoleSourceMismatch) as raised:
            BlockRoster(manifest, other_role)
        assert COORDINATE in str(raised.value)

    @pytest.mark.parametrize(
        "error", [NoShardArtifacts, UnsizedBlock, UnverifiableBlock, RoleSourceMismatch]
    )
    def test_every_guard_shares_one_base(self, error):
        assert issubclass(error, RosterError)
