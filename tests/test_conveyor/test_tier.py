"""Tests for one tier's byte-budgeted residency and the derived-artifact layout.

Mirrors ``src/molhub/conveyor/tier.py``. The ledger is a fake implementing the
three verbs :class:`~molhub.conveyor.tier.BlockLedger` names and nothing else —
ac-001 requires this module to run without importing ``-01``'s real
:class:`~molhub.conveyor.ledger.Ledger`, so that a tier failure is never a
ledger failure wearing a different hat. That the landed ``Ledger`` still fits
the seam is proved in ``test_layering.py``, where the import is free.

Shapes the spec leaves implicit, decided here because a test cannot avoid
picking one:

* ``entries()`` is a mapping of resident block to the bytes it is charged, so
  "the entry set" and "what each entry costs" are one read rather than two.
  Every assertion but one goes through ``set(store.entries())``, which holds
  for any iterable of block ids as well.
* ``evict_until(n)`` frees *at least* ``n`` bytes and stops at the first
  candidate that meets the target; the fixtures start at exactly full so both
  readings of the target (bytes freed / headroom reached) coincide.
* Constructing a store over a directory that already exceeds its budget
  **reports** the excess instead of refusing — ``molhub cache status`` exists to
  print exactly that, and a constructor that raised would make the invariant
  failure unobservable.
* A refused ``write_metadata`` and a ``VisitOrder`` handed to ``admit`` are
  typed refusals; the family base :class:`~molhub.conveyor.block.ConveyorError`
  is asserted rather than the leaf, so naming the leaf stays the implementer's
  choice. A bare ``AttributeError`` is not a refusal and fails these tests.
* ``write_metadata`` is given a directory that already exists, so whether
  ``artifact_dir`` creates it is left open.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path

import pytest

from molhub.conveyor.block import BlockId, BlockState, ConveyorError
from molhub.conveyor.tier import (
    BlockNotResident,
    BlockUnevictable,
    DerivedLayout,
    TierError,
    TierOverBudget,
    TierStore,
    VisitOrder,
)

SOURCE = "dataset:themol/mbis@1"
TASK = "electrostatic"

# Every fixture block is 1 000 declared bytes, so a budget is readable as a
# block count without the test having to do arithmetic in its head.
BLOCK_BYTES = 1_000

RAW_SUBDIR = "conveyor/raw"
BLOCKS_SUBDIR = "conveyor/blocks"

HOLDER = "plan:test"


def _block(name: str, *, split: str | None = "train") -> BlockId:
    """One fixture block; only ``block_id`` varies, so key order is name order."""
    return BlockId(SOURCE, TASK, split, name)


B00, B01, B02, B03, B04 = (_block(f"b{index:02d}") for index in range(5))


@dataclasses.dataclass(frozen=True)
class AppendCall:
    """One recorded ``append`` — the only ledger write a tier is allowed."""

    block: BlockId
    state: BlockState
    size_bytes: int | None


class FakeLedger:
    """A ``BlockLedger``: block state, live leases, record append. Nothing else.

    The three verbs are spelled as ``-01`` spells them (``replay`` /
    ``active_leases`` / ``append``), because the protocol is a read/append
    *view* of that ledger and a second spelling would be a second ledger.

    Args:
        states: Initial block -> state, as ``replay`` would return it.
        leases: Initial block -> holders, as ``active_leases`` would.
    """

    def __init__(
        self,
        *,
        states: Mapping[BlockId, BlockState] | None = None,
        leases: Mapping[BlockId, tuple[str, ...]] | None = None,
    ) -> None:
        self._states: dict[BlockId, BlockState] = dict(states or {})
        self._leases: dict[BlockId, tuple[str, ...]] = dict(leases or {})
        self.appends: list[AppendCall] = []

    def replay(self) -> Mapping[BlockId, BlockState]:
        """The last state recorded for every block this ledger mentions."""
        return dict(self._states)

    def active_leases(self, *, now: datetime | None = None) -> Mapping[BlockId, tuple[str, ...]]:
        """Who currently holds which block."""
        return dict(self._leases)

    def append(
        self,
        block: BlockId,
        state: BlockState,
        *,
        size_bytes: int | None = None,
        payload: Mapping[str, str] | None = None,
    ) -> None:
        """Record that *block* reached *state*."""
        self.appends.append(AppendCall(block, state, size_bytes))
        self._states[block] = state

    # -- test-side controls, never part of the protocol --------------------

    def mark(self, blocks: Iterable[BlockId], state: BlockState) -> None:
        """Put *blocks* into *state* without going through ``append``."""
        for block in blocks:
            self._states[block] = state

    def grant(self, block: BlockId, holder: str = HOLDER) -> None:
        """Give *holder* a live lease on *block*."""
        self._leases[block] = (holder,)

    @property
    def states(self) -> tuple[BlockState, ...]:
        """Every state appended, in order."""
        return tuple(call.state for call in self.appends)


def _store(
    root: Path,
    ledger: FakeLedger,
    *,
    subdir: str = BLOCKS_SUBDIR,
    budget_bytes: int = 3 * BLOCK_BYTES,
) -> TierStore:
    """A tier over *root*; the blocks tier at three blocks unless told otherwise."""
    return TierStore(root, subdir=subdir, budget_bytes=budget_bytes, ledger=ledger)


def _filled(
    root: Path,
    ledger: FakeLedger,
    blocks: Iterable[BlockId],
    *,
    subdir: str = BLOCKS_SUBDIR,
    budget_bytes: int = 3 * BLOCK_BYTES,
) -> TierStore:
    """A tier holding *blocks*, each charged :data:`BLOCK_BYTES`, with bytes on disk."""
    store = _store(root, ledger, subdir=subdir, budget_bytes=budget_bytes)
    for block in blocks:
        directory = store.admit(block, nbytes=BLOCK_BYTES)
        (directory / "column.bin").write_bytes(b"\0" * BLOCK_BYTES)
    return store


class TestTierStore:
    """One subdirectory, one budget, one kind of ledger record."""

    def test_admit_returns_a_path_inside_this_tiers_subdirectory(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        assert store.admit(B00, nbytes=BLOCK_BYTES).is_relative_to(tmp_path / "conveyor" / "blocks")

    def test_admit_creates_the_directory(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        assert store.admit(B00, nbytes=BLOCK_BYTES).is_dir()

    def test_path_for_is_inside_this_tiers_subdirectory(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        assert store.path_for(B00).is_relative_to(tmp_path / "conveyor" / "blocks")

    def test_path_for_creates_nothing(self, tmp_path):
        """``path_for`` answers where; only ``admit`` records that anything is there."""
        store = _store(tmp_path, FakeLedger())
        assert not store.path_for(B00).exists()

    def test_path_for_charges_nothing(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        store.path_for(B00)
        assert store.resident_bytes == 0

    def test_admit_charges_the_declared_bytes_before_they_exist(self, tmp_path):
        """A shard must be admitted before its bytes land, so the budget is declared."""
        store = _store(tmp_path, FakeLedger())
        store.admit(B00, nbytes=BLOCK_BYTES)
        assert store.resident_bytes == BLOCK_BYTES

    def test_headroom_is_the_budget_less_what_is_resident(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        store.admit(B00, nbytes=BLOCK_BYTES)
        assert store.headroom == 2 * BLOCK_BYTES

    def test_entries_charge_each_resident_block_its_declared_bytes(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        store.admit(B00, nbytes=BLOCK_BYTES)
        assert dict(store.entries()) == {B00: BLOCK_BYTES}

    def test_an_admission_that_does_not_fit_is_refused(self, tmp_path):
        """No silent eviction: a stage out of room decides whether to stall or evict."""
        store = _store(tmp_path, FakeLedger(), budget_bytes=BLOCK_BYTES)
        store.admit(B00, nbytes=BLOCK_BYTES)
        with pytest.raises(TierOverBudget):
            store.admit(B01, nbytes=BLOCK_BYTES)

    def test_a_refused_admission_charges_nothing(self, tmp_path):
        store = _store(tmp_path, FakeLedger(), budget_bytes=BLOCK_BYTES)
        store.admit(B00, nbytes=BLOCK_BYTES)
        with pytest.raises(TierOverBudget):
            store.admit(B01, nbytes=BLOCK_BYTES)
        assert store.resident_bytes == BLOCK_BYTES
        assert set(store.entries()) == {B00}

    def test_a_refused_admission_creates_no_directory(self, tmp_path):
        store = _store(tmp_path, FakeLedger(), budget_bytes=BLOCK_BYTES)
        store.admit(B00, nbytes=BLOCK_BYTES)
        with pytest.raises(TierOverBudget):
            store.admit(B01, nbytes=BLOCK_BYTES)
        assert not store.path_for(B01).exists()

    def test_a_refused_admission_names_only_the_tier_it_was_called_on(self, tmp_path):
        """ac-002: pressure is reported against one subdirectory, never both."""
        store = _store(tmp_path, FakeLedger(), budget_bytes=BLOCK_BYTES)
        store.admit(B00, nbytes=BLOCK_BYTES)
        with pytest.raises(TierOverBudget) as error:
            store.admit(B01, nbytes=BLOCK_BYTES)
        assert BLOCKS_SUBDIR in str(error.value)
        assert RAW_SUBDIR not in str(error.value)

    def test_the_default_root_is_the_blob_stores(self, tmp_path, monkeypatch):
        """ac-001: ``$MOLHUB_HOME`` is read in exactly one place in the repo."""
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path))
        store = TierStore(subdir=BLOCKS_SUBDIR, budget_bytes=BLOCK_BYTES, ledger=FakeLedger())
        assert store.path_for(B00).is_relative_to(tmp_path / "conveyor" / "blocks")

    def test_the_tier_is_not_under_the_cross_client_files_layout(self, tmp_path):
        """``files/`` is what the TypeScript client reads; a tier is not an artifact."""
        store = _store(tmp_path, FakeLedger())
        assert not store.path_for(B00).is_relative_to(tmp_path / "files")

    def test_residency_is_re_derived_from_disk_at_construction(self, tmp_path):
        """I5: residency survives a crash from files present, with no recovery verb."""
        first = _store(tmp_path, FakeLedger())
        directory = first.admit(B00, nbytes=BLOCK_BYTES)
        (directory / "column.bin").write_bytes(b"\0" * 512)
        assert _store(tmp_path, FakeLedger()).resident_bytes == 512

    def test_a_re_derived_entry_is_charged_every_file_it_holds(self, tmp_path):
        first = _store(tmp_path, FakeLedger())
        directory = first.admit(B00, nbytes=BLOCK_BYTES)
        (directory / "column.bin").write_bytes(b"\0" * 512)
        (directory / "manifest.json").write_bytes(b"\0" * 8)
        assert _store(tmp_path, FakeLedger()).resident_bytes == 520

    def test_a_re_derived_tier_holds_the_blocks_on_disk(self, tmp_path):
        first = _store(tmp_path, FakeLedger())
        (first.admit(B00, nbytes=BLOCK_BYTES) / "column.bin").write_bytes(b"\0" * 512)
        assert set(_store(tmp_path, FakeLedger()).entries()) == {B00}

    def test_construction_reports_an_over_budget_directory_rather_than_refusing(self, tmp_path):
        """``molhub cache status`` exits 1 on this; a raising constructor hides it."""
        first = _store(tmp_path, FakeLedger())
        (first.admit(B00, nbytes=BLOCK_BYTES) / "column.bin").write_bytes(b"\0" * 4096)
        assert _store(tmp_path, FakeLedger(), budget_bytes=1024).resident_bytes == 4096

    def test_release_deletes_this_tiers_copy(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00])
        store.release(B00)
        assert not store.path_for(B00).exists()

    def test_release_frees_the_bytes(self, tmp_path):
        store = _filled(tmp_path, FakeLedger(), [B00])
        store.release(B00)
        assert store.resident_bytes == 0
        assert set(store.entries()) == set()

    def test_release_refuses_a_leased_block(self, tmp_path):
        """I9: a byte budget never wins against a live lease."""
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00])
        ledger.grant(B00)
        with pytest.raises(BlockUnevictable):
            store.release(B00)

    def test_a_leased_block_survives_the_refusal(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00])
        ledger.grant(B00)
        with pytest.raises(BlockUnevictable):
            store.release(B00)
        assert store.path_for(B00).is_dir()
        assert store.resident_bytes == BLOCK_BYTES

    def test_release_refuses_a_resident_flagged_block(self, tmp_path):
        """The T-HOT exemption: validation sets and the Hessian core stay put."""
        store = _filled(tmp_path, FakeLedger(), [B00])
        store.flag_resident(B00)
        with pytest.raises(BlockUnevictable):
            store.release(B00)

    def test_release_of_a_block_this_tier_never_admitted_is_refused(self, tmp_path):
        store = _filled(tmp_path, FakeLedger(), [B00])
        with pytest.raises(BlockNotResident):
            store.release(B01)

    def test_flag_resident_is_idempotent(self, tmp_path):
        store = _filled(tmp_path, FakeLedger(), [B00])
        store.flag_resident(B00)
        store.flag_resident(B00)
        assert dict(store.entries()) == {B00: BLOCK_BYTES}

    def test_the_eviction_order_is_the_visit_plan(self, tmp_path):
        """ac-004, as an exact tuple: absent, behind ascending, ahead descending, tie.

        ``B02`` and ``B04`` are absent from the plan (coldest, tied, so ascending
        block id decides); ``B01`` and ``B03`` sit behind the cursor at positions
        0 and 1; ``B00`` sits at the cursor itself and is therefore the nearest
        future, evicted last.
        """
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01, B02, B03, B04], budget_bytes=5 * BLOCK_BYTES)
        ledger.mark([B00, B01, B02, B03, B04], BlockState.CONSUMED)
        plan = VisitOrder((B01, B03, B00), cursor=2)
        assert store.evict_until(5 * BLOCK_BYTES, plan=plan) == (B02, B04, B01, B03, B00)

    def test_eviction_stops_once_the_target_is_met(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01, B02, B03, B04], budget_bytes=5 * BLOCK_BYTES)
        ledger.mark([B00, B01, B02, B03, B04], BlockState.CONSUMED)
        plan = VisitOrder((B01, B03, B00), cursor=2)
        assert store.evict_until(2 * BLOCK_BYTES, plan=plan) == (B02, B04)

    def test_what_eviction_kept_is_still_resident(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01, B02, B03, B04], budget_bytes=5 * BLOCK_BYTES)
        ledger.mark([B00, B01, B02, B03, B04], BlockState.CONSUMED)
        store.evict_until(2 * BLOCK_BYTES, plan=VisitOrder((B01, B03, B00), cursor=2))
        assert set(store.entries()) == {B00, B01, B03}
        assert store.resident_bytes == 3 * BLOCK_BYTES

    def test_eviction_deletes_the_bytes_it_reported(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01], budget_bytes=2 * BLOCK_BYTES)
        ledger.mark([B00, B01], BlockState.CONSUMED)
        store.evict_until(BLOCK_BYTES, plan=VisitOrder((B01,), cursor=0))
        assert not store.path_for(B00).exists()

    def test_eviction_skips_a_block_that_is_not_consumed(self, tmp_path):
        """READY means someone still has it to read; only CONSUMED is a candidate."""
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01], budget_bytes=2 * BLOCK_BYTES)
        ledger.mark([B00], BlockState.READY)
        ledger.mark([B01], BlockState.CONSUMED)
        assert store.evict_until(BLOCK_BYTES, plan=VisitOrder((), cursor=0)) == (B01,)

    def test_eviction_skips_a_leased_block(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01], budget_bytes=2 * BLOCK_BYTES)
        ledger.mark([B00, B01], BlockState.CONSUMED)
        ledger.grant(B00)
        assert store.evict_until(BLOCK_BYTES, plan=VisitOrder((), cursor=0)) == (B01,)

    def test_eviction_skips_a_resident_flagged_block(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01], budget_bytes=2 * BLOCK_BYTES)
        ledger.mark([B00, B01], BlockState.CONSUMED)
        store.flag_resident(B00)
        assert store.evict_until(BLOCK_BYTES, plan=VisitOrder((), cursor=0)) == (B01,)

    def test_an_infeasible_eviction_is_refused(self, tmp_path):
        """Stalling is the correct failure; breaking a lease is not."""
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01], budget_bytes=2 * BLOCK_BYTES)
        ledger.mark([B00, B01], BlockState.CONSUMED)
        ledger.grant(B00)
        store.flag_resident(B01)
        with pytest.raises(TierOverBudget):
            store.evict_until(BLOCK_BYTES, plan=VisitOrder((), cursor=0))

    def test_an_infeasible_eviction_deletes_nothing(self, tmp_path):
        """ac-003: feasibility is checked before the first unlink, not during."""
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01, B02], budget_bytes=3 * BLOCK_BYTES)
        ledger.mark([B00, B01, B02], BlockState.CONSUMED)
        ledger.grant(B00)
        store.flag_resident(B01)
        with pytest.raises(TierOverBudget):
            store.evict_until(3 * BLOCK_BYTES, plan=VisitOrder((), cursor=0))
        assert store.resident_bytes == 3 * BLOCK_BYTES
        assert set(store.entries()) == {B00, B01, B02}
        assert all(store.path_for(block).is_dir() for block in (B00, B01, B02))

    def test_an_infeasible_eviction_names_the_blocked_candidates(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01], budget_bytes=2 * BLOCK_BYTES)
        ledger.mark([B00, B01], BlockState.CONSUMED)
        ledger.grant(B00)
        store.flag_resident(B01)
        with pytest.raises(TierOverBudget) as error:
            store.evict_until(BLOCK_BYTES, plan=VisitOrder((), cursor=0))
        assert B00.block_id in str(error.value)
        assert B01.block_id in str(error.value)

    def test_release_appends_exactly_one_remote_record(self, tmp_path):
        """A block with nothing local *is* REMOTE; no fifth state is invented."""
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00])
        store.release(B00)
        assert ledger.appends == [AppendCall(B00, BlockState.REMOTE, BLOCK_BYTES)]

    def test_eviction_appends_one_remote_record_per_deletion(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00, B01], budget_bytes=2 * BLOCK_BYTES)
        ledger.mark([B00, B01], BlockState.CONSUMED)
        store.evict_until(2 * BLOCK_BYTES, plan=VisitOrder((), cursor=0))
        assert ledger.appends == [
            AppendCall(B00, BlockState.REMOTE, BLOCK_BYTES),
            AppendCall(B01, BlockState.REMOTE, BLOCK_BYTES),
        ]

    def test_admit_appends_no_ledger_record(self, tmp_path):
        ledger = FakeLedger()
        _store(tmp_path, ledger).admit(B00, nbytes=BLOCK_BYTES)
        assert ledger.appends == []

    def test_path_for_appends_no_ledger_record(self, tmp_path):
        ledger = FakeLedger()
        _store(tmp_path, ledger).path_for(B00)
        assert ledger.appends == []

    def test_flag_resident_appends_no_ledger_record(self, tmp_path):
        """Residency is a flag this stage owns, not a transition the ledger records."""
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00])
        store.flag_resident(B00)
        assert ledger.appends == []

    def test_a_failed_eviction_appends_no_ledger_record(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00], budget_bytes=BLOCK_BYTES)
        ledger.grant(B00)
        with pytest.raises(TierOverBudget):
            store.evict_until(BLOCK_BYTES, plan=VisitOrder((), cursor=0))
        assert ledger.appends == []

    def test_a_refused_release_appends_no_ledger_record(self, tmp_path):
        ledger = FakeLedger()
        store = _filled(tmp_path, ledger, [B00])
        ledger.grant(B00)
        with pytest.raises(BlockUnevictable):
            store.release(B00)
        assert ledger.appends == []

    def test_two_tiers_over_one_root_hold_different_subdirectories(self, tmp_path):
        ledger = FakeLedger()
        raw = _store(tmp_path, ledger, subdir=RAW_SUBDIR, budget_bytes=2 * BLOCK_BYTES)
        blocks = _store(tmp_path, ledger, subdir=BLOCKS_SUBDIR, budget_bytes=3 * BLOCK_BYTES)
        assert raw.path_for(B00) != blocks.path_for(B00)

    def test_a_tier_does_not_see_the_other_tiers_entries(self, tmp_path):
        """ac-002: two instances, two budgets, no shared counter and no shared set."""
        ledger = FakeLedger()
        raw = _filled(
            tmp_path,
            ledger,
            [_block("shard-000", split=None)],
            subdir=RAW_SUBDIR,
            budget_bytes=2 * BLOCK_BYTES,
        )
        blocks = _filled(tmp_path, ledger, [B00], subdir=BLOCKS_SUBDIR)
        assert set(blocks.entries()) == {B00}
        assert set(raw.entries()) == {_block("shard-000", split=None)}

    def test_pressure_on_one_tier_leaves_the_other_untouched(self, tmp_path):
        ledger = FakeLedger()
        shard = _block("shard-000", split=None)
        raw = _filled(tmp_path, ledger, [shard], subdir=RAW_SUBDIR, budget_bytes=2 * BLOCK_BYTES)
        blocks = _filled(tmp_path, ledger, [B00, B01, B02], subdir=BLOCKS_SUBDIR)
        ledger.mark([B00, B01, B02], BlockState.CONSUMED)
        blocks.evict_until(3 * BLOCK_BYTES, plan=VisitOrder((), cursor=0))
        assert raw.resident_bytes == BLOCK_BYTES
        assert set(raw.entries()) == {shard}
        assert raw.path_for(shard).is_dir()

    def test_the_error_family_is_one_tier_error(self):
        """One typed failure per distinguishable defect, under one catchable base."""
        assert issubclass(TierError, ConveyorError)
        assert issubclass(TierOverBudget, TierError)
        assert issubclass(BlockUnevictable, TierError)
        assert issubclass(BlockNotResident, TierError)


class TestVisitOrder:
    """The consumer's plan: metadata only, and never a tier entry."""

    def test_it_carries_the_order_it_was_given(self):
        assert VisitOrder((B01, B03, B00), cursor=2).order == (B01, B03, B00)

    def test_it_carries_the_cursor(self):
        assert VisitOrder((B01, B03, B00), cursor=2).cursor == 2

    def test_it_is_frozen(self):
        plan = VisitOrder((B01, B03, B00), cursor=2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.cursor = 3  # type: ignore[misc]

    def test_position_names_the_slot_a_block_occupies(self):
        """House vocabulary: ``position`` / ``cursor``, never ``index``."""
        assert VisitOrder((B01, B03, B00), cursor=2).position(B03) == 1

    def test_a_block_absent_from_the_plan_has_no_position(self):
        assert VisitOrder((B01, B03, B00), cursor=2).position(B04) is None

    def test_a_plan_is_never_admitted_to_a_tier(self):
        """ac-004: nothing in a tier represents the plan, so nothing can evict it."""
        assert not isinstance(VisitOrder((B01,), cursor=0), BlockId)

    def test_admit_refuses_a_plan(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        with pytest.raises((TypeError, ConveyorError)):
            store.admit(VisitOrder((B01,), cursor=0), nbytes=BLOCK_BYTES)  # type: ignore[arg-type]

    def test_a_refused_plan_occupies_no_entry(self, tmp_path):
        store = _store(tmp_path, FakeLedger())
        with pytest.raises((TypeError, ConveyorError)):
            store.admit(VisitOrder((B01,), cursor=0), nbytes=BLOCK_BYTES)  # type: ignore[arg-type]
        assert set(store.entries()) == set()
        assert store.resident_bytes == 0


# The document `scripts/build_class1_splits.py` writes, shortened to five keys
# and stripped of anything that varies per run. The key order is deliberately
# not alphabetical: `json.dumps` preserves insertion order, the script relies on
# that, and a `sort_keys=True` here would change the bytes of every metadata.json
# already shipped under `derived/molcrafts/class1-universal-splits/1`.
METADATA_DOCUMENT = {
    "coordinate": "dataset:molcrafts/class1-universal-splits@1",
    "seed": 20260814,
    "generated_at": "2026-08-14T00:00:00",
    "generator": "scripts/build_class1_splits.py",
    "output_sha256": {
        "identity_splits.csv.gz": (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
    },
}

# Written out by hand rather than round-tripped through `json.dumps`, because
# ac-006 is a *byte* claim: indent=2, insertion order, one trailing newline.
EXPECTED_METADATA_BYTES = (
    "{\n"
    '  "coordinate": "dataset:molcrafts/class1-universal-splits@1",\n'
    '  "seed": 20260814,\n'
    '  "generated_at": "2026-08-14T00:00:00",\n'
    '  "generator": "scripts/build_class1_splits.py",\n'
    '  "output_sha256": {\n'
    '    "identity_splits.csv.gz": '
    '"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"\n'
    "  }\n"
    "}\n"
).encode("utf-8")


class TestDerivedLayout:
    """One rule for coordinate-shaped derived artifacts, two users."""

    def test_the_artifact_directory_is_coordinate_shaped(self, tmp_path):
        layout = DerivedLayout(tmp_path, subdir="derived")
        assert layout.artifact_dir("molcrafts", "class1-universal-splits", "1") == (
            tmp_path / "derived" / "molcrafts" / "class1-universal-splits" / "1"
        )

    def test_the_artifact_directory_is_under_the_layouts_own_subdirectory(self, tmp_path):
        layout = DerivedLayout(tmp_path, subdir="conveyor/blocks")
        assert layout.artifact_dir("themol", "mbis", "1").is_relative_to(
            tmp_path / "conveyor" / "blocks"
        )

    def test_write_metadata_writes_the_bytes_the_splits_script_writes(self, tmp_path):
        """ac-006: byte-identical to today's output for the same document."""
        layout = DerivedLayout(tmp_path, subdir="derived")
        directory = layout.artifact_dir("molcrafts", "class1-universal-splits", "1")
        directory.mkdir(parents=True, exist_ok=True)
        layout.write_metadata(directory, METADATA_DOCUMENT)
        assert (directory / "metadata.json").read_bytes() == EXPECTED_METADATA_BYTES

    def test_write_metadata_round_trips_the_document(self, tmp_path):
        layout = DerivedLayout(tmp_path, subdir="derived")
        directory = layout.artifact_dir("molcrafts", "class1-universal-splits", "1")
        directory.mkdir(parents=True, exist_ok=True)
        layout.write_metadata(directory, METADATA_DOCUMENT)
        loaded = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        assert loaded == METADATA_DOCUMENT

    def test_write_metadata_leaves_no_temporary_file_behind(self, tmp_path):
        """tmp -> fsync -> os.replace: no reader ever sees a partial document."""
        layout = DerivedLayout(tmp_path, subdir="derived")
        directory = layout.artifact_dir("molcrafts", "class1-universal-splits", "1")
        directory.mkdir(parents=True, exist_ok=True)
        layout.write_metadata(directory, METADATA_DOCUMENT)
        assert [path.name for path in directory.iterdir()] == ["metadata.json"]

    def test_write_metadata_replaces_an_earlier_document(self, tmp_path):
        layout = DerivedLayout(tmp_path, subdir="derived")
        directory = layout.artifact_dir("molcrafts", "class1-universal-splits", "1")
        directory.mkdir(parents=True, exist_ok=True)
        layout.write_metadata(directory, {**METADATA_DOCUMENT, "seed": 1})
        layout.write_metadata(directory, METADATA_DOCUMENT)
        assert (directory / "metadata.json").read_bytes() == EXPECTED_METADATA_BYTES

    def test_a_document_without_a_generator_is_refused(self, tmp_path):
        """Who derived this is the one provenance question a path cannot answer."""
        layout = DerivedLayout(tmp_path, subdir="derived")
        directory = layout.artifact_dir("molcrafts", "class1-universal-splits", "1")
        directory.mkdir(parents=True, exist_ok=True)
        document = {key: value for key, value in METADATA_DOCUMENT.items() if key != "generator"}
        with pytest.raises(ConveyorError):
            layout.write_metadata(directory, document)

    def test_a_document_without_a_generated_at_is_refused(self, tmp_path):
        layout = DerivedLayout(tmp_path, subdir="derived")
        directory = layout.artifact_dir("molcrafts", "class1-universal-splits", "1")
        directory.mkdir(parents=True, exist_ok=True)
        document = {key: value for key, value in METADATA_DOCUMENT.items() if key != "generated_at"}
        with pytest.raises(ConveyorError):
            layout.write_metadata(directory, document)

    def test_a_refused_document_writes_nothing(self, tmp_path):
        layout = DerivedLayout(tmp_path, subdir="derived")
        directory = layout.artifact_dir("molcrafts", "class1-universal-splits", "1")
        directory.mkdir(parents=True, exist_ok=True)
        document = {key: value for key, value in METADATA_DOCUMENT.items() if key != "generator"}
        with pytest.raises(ConveyorError):
            layout.write_metadata(directory, document)
        assert list(directory.iterdir()) == []
