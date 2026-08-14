"""Tests for block identity and the four-state block lifecycle.

Mirrors ``src/molhub/conveyor/block.py``. The legality table below is
transcribed from the spec (`streaming-data-tiers-03-conveyor-01-ledger` § 2) and
is the whole point of the file: an impossible block history must be
unrepresentable, so every one of the sixteen ordered pairs is decided here
rather than left to whatever the implementation happens to allow.
"""

from __future__ import annotations

import dataclasses
import itertools
from types import MappingProxyType

import pytest

from molhub.conveyor import block as block_module
from molhub.conveyor.block import (
    BlockId,
    BlockState,
    IllegalTransition,
    InvalidBlockId,
    UnknownBlockState,
)
from molhub.coordinate import InvalidCoordinate

_REMOTE = BlockState.REMOTE
_DOWNLOADING = BlockState.DOWNLOADING
_READY = BlockState.READY
_CONSUMED = BlockState.CONSUMED

# The spec's 4x4 table, verbatim: ten legal pairs, six illegal.  Self-
# transitions are legal on purpose — every conveyor stage must be idempotent
# after a crash, so re-running one records a fact instead of raising.
LEGALITY: dict[tuple[BlockState, BlockState], bool] = {
    (_REMOTE, _REMOTE): True,  # idempotent re-declare
    (_REMOTE, _DOWNLOADING): True,  # fetch starts
    (_REMOTE, _READY): False,  # the half-ready hole I5 exists to close
    (_REMOTE, _CONSUMED): False,  # consuming what was never local
    (_DOWNLOADING, _REMOTE): True,  # failure / digest mismatch; partial dropped
    (_DOWNLOADING, _DOWNLOADING): True,  # idempotent re-attempt / resume
    (_DOWNLOADING, _READY): True,  # unpack AND prepare AND verify succeeded
    (_DOWNLOADING, _CONSUMED): False,  # never consume unverified bytes
    (_READY, _REMOTE): True,  # released without being consumed (I4 eviction)
    (_READY, _DOWNLOADING): False,  # a re-fetch restarts from REMOTE
    (_READY, _READY): True,  # idempotent re-verify
    (_READY, _CONSUMED): True,  # consumed
    (_CONSUMED, _REMOTE): True,  # deleted locally; a later pass re-fetches
    (_CONSUMED, _DOWNLOADING): False,  # must re-declare REMOTE first
    (_CONSUMED, _READY): False,
    (_CONSUMED, _CONSUMED): True,  # several consumers finishing
}

_ORDERED_PAIRS = [
    pytest.param(origin, target, legal, id=f"{origin.value}-to-{target.value}")
    for (origin, target), legal in LEGALITY.items()
]

_GOOD_SOURCE = "dataset:themol/torsion-scan@1"


def _block(**overrides: object) -> BlockId:
    """A valid :class:`BlockId` with *overrides* applied to one field."""
    fields: dict[str, object] = {
        "source": _GOOD_SOURCE,
        "task": "torsion",
        "split": "train",
        "block_id": "shard-003",
    }
    fields.update(overrides)
    return BlockId(**fields)  # type: ignore[arg-type]


def _legality_map() -> MappingProxyType[BlockState, frozenset[BlockState]]:
    """The module-level legality mapping, located by shape rather than by name.

    The spec pins the mapping's *shape* — module level, ``MappingProxyType``
    over ``frozenset``s, keyed by exactly the four members — but never fixes a
    name for it, so pinning a name here would invent contract the spec does not
    have.
    """
    found = {
        name: value
        for name, value in vars(block_module).items()
        if not name.startswith("__") and isinstance(value, MappingProxyType)
    }
    assert len(found) == 1, f"expected exactly one frozen mapping in block.py, got {sorted(found)}"
    return next(iter(found.values()))


class TestBlockState:
    """The closed four-state machine and its frozen legality map."""

    def test_the_table_decides_every_ordered_pair(self):
        """A transcription that missed a pair would silently prove less."""
        assert set(LEGALITY) == set(itertools.product(BlockState, repeat=2))

    def test_the_table_is_ten_legal_and_six_illegal(self):
        legal = sum(1 for allowed in LEGALITY.values() if allowed)
        assert (legal, len(LEGALITY) - legal) == (10, 6)

    def test_there_are_exactly_four_states(self):
        """A fifth state is what I5 forbids; residency is a flag, not a state."""
        assert len(BlockState) == 4

    @pytest.mark.parametrize(("origin", "target", "legal"), _ORDERED_PAIRS)
    def test_may_become_matches_the_table(self, origin, target, legal):
        assert origin.may_become(target) is legal

    @pytest.mark.parametrize(("origin", "target", "legal"), _ORDERED_PAIRS)
    def test_transition_to_enforces_the_table(self, origin, target, legal):
        if legal:
            assert origin.transition_to(target) is target
            return
        with pytest.raises(IllegalTransition) as excinfo:
            origin.transition_to(target)
        message = str(excinfo.value).lower()
        # Every member's name lower-cases to its value, so this accepts either
        # spelling while still requiring both endpoints to be named.
        assert origin.value in message and target.value in message

    def test_every_ordered_pair_is_answered(self):
        """A member added without a legality row must not raise a KeyError."""
        answers = {
            (origin, target): origin.may_become(target)
            for origin, target in itertools.product(BlockState, repeat=2)
        }
        assert all(isinstance(answer, bool) for answer in answers.values())

    def test_the_legality_map_is_keyed_by_exactly_the_members(self):
        assert set(_legality_map()) == set(BlockState)

    def test_the_legality_rows_are_frozen_sets_of_states(self):
        for origin, targets in _legality_map().items():
            assert isinstance(targets, frozenset), origin
            assert all(isinstance(target, BlockState) for target in targets), origin

    @pytest.mark.parametrize("state", list(BlockState), ids=lambda s: s.value)
    def test_parse_round_trips_every_member(self, state):
        assert BlockState.parse(state.value) is state

    def test_parse_rejects_an_unknown_name(self):
        with pytest.raises(UnknownBlockState):
            BlockState.parse("half-ready")

    def test_parse_names_the_text_it_refused(self):
        with pytest.raises(UnknownBlockState, match="half-ready"):
            BlockState.parse("half-ready")


class TestBlockId:
    """The strategy's four-tuple: validated at construction, never sanitised."""

    def test_key_matches_the_documented_layout(self):
        block = BlockId("dataset:themol/torsion-scan@1", "torsion", "train", "shard-003")
        assert block.key() == "dataset/themol/torsion-scan@1/torsion/train/shard-003"

    def test_key_uses_the_reserved_unsplit_segment_when_split_is_none(self):
        block = BlockId("dataset:themol/mbis@1", "electrostatic", None, "shard-003")
        assert block.key() == "dataset/themol/mbis@1/electrostatic/unsplit/shard-003"

    def test_a_split_mixed_block_is_representable(self):
        """``None`` is the honest encoding of "not split-pure" — see -02-roster."""
        assert _block(split=None).split is None

    def test_a_real_split_and_a_mixed_block_get_different_keys(self):
        assert _block(split="train").key() != _block(split=None).key()

    def test_equality_is_by_value(self):
        assert _block() == _block()

    def test_a_different_split_is_a_different_block(self):
        assert _block(split="train") != _block(split="val")

    def test_hashable_by_value(self):
        assert len({_block(), _block()}) == 1

    def test_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            _block().block_id = "shard-004"  # type: ignore[misc]

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"task": ""}, id="empty-task"),
            pytest.param({"split": ""}, id="empty-split"),
            pytest.param({"block_id": ""}, id="empty-block-id"),
            pytest.param({"source": ""}, id="empty-source"),
        ],
    )
    def test_empty_fields_are_rejected(self, overrides):
        with pytest.raises(InvalidBlockId):
            _block(**overrides)

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"block_id": "shard/003"}, id="slash-in-block-id"),
            pytest.param({"task": "torsion/scan"}, id="slash-in-task"),
            pytest.param({"split": "train/val"}, id="slash-in-split"),
        ],
    )
    def test_path_separators_are_rejected_not_sanitised(self, overrides):
        """A sanitiser would collapse two distinct blocks onto one key."""
        with pytest.raises(InvalidBlockId):
            _block(**overrides)

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"split": "train val"}, id="space-in-split"),
            pytest.param({"block_id": "shard 003"}, id="space-in-block-id"),
        ],
    )
    def test_whitespace_is_rejected(self, overrides):
        with pytest.raises(InvalidBlockId):
            _block(**overrides)

    def test_the_reserved_unsplit_value_is_rejected_as_a_split(self):
        """``key()`` spends "unsplit" on ``split is None``; a real one would collide."""
        with pytest.raises(InvalidBlockId):
            _block(split="unsplit")

    def test_a_source_that_is_not_a_coordinate_is_rejected(self):
        with pytest.raises(InvalidBlockId):
            _block(source="notebook:themol/torsion-scan@1")

    def test_the_coordinate_parse_error_is_kept_as_the_cause(self):
        with pytest.raises(InvalidBlockId) as excinfo:
            _block(source="notebook:themol/torsion-scan@1")
        assert isinstance(excinfo.value.__cause__, InvalidCoordinate)

    def test_an_unversioned_source_is_rejected(self):
        """Version pinning is a molhub never-change rule, not a default."""
        with pytest.raises(InvalidBlockId):
            _block(source="dataset:themol/torsion-scan")
