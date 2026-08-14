"""Tests for byte-weighted admission control and the prepare worker pool.

Mirrors ``src/molhub/conveyor/backpressure.py``. The binding contract is the
``timeout=0`` probe — full raises :class:`~molhub.conveyor.backpressure.QueueTimeout`,
freed admits — which is single-threaded, sleep-free and wall-clock-free.
**There is exactly one threaded test in this file** (a genuinely blocked
``reserve`` waking on ``release``), it hands off through a
:class:`threading.Event` and bounds itself with ``join(timeout=5)``, and there
is no ``time.sleep`` anywhere in the module. A queue test that sleeps is a queue
test that gets marked slow and then skipped.

Shapes the spec leaves implicit, decided here because a test cannot avoid
picking one:

* ``ByteBoundedQueue(capacity_bytes=...)`` — the capacity is keyword-named for
  the same reason ``TierStore``'s budget is: a bare number that could be a count
  or a byte size is exactly the confusion I4 is about.
* ``take`` mirrors ``reserve``'s timeout rule, so ``take(timeout=0)`` on an
  empty queue raises ``QueueTimeout`` rather than returning a sentinel.
* ``PrepareWorkers`` exposes the multiprocessing context it will spawn with;
  :func:`_context_of` accepts either spelling (``mp_context`` / ``context``), so
  ac-009 is pinned on the *value* and the attribute name stays open.
* ``collect`` returns one outcome per call — there is no ``run_all``, so the
  submit/collect loop is the caller's — and with two workers the order of two
  outcomes is not asserted.
* ``FakeRunner`` is deliberately not ``THEMolUnitEncoder``: the pool contract is
  "any object with ``run(job)`` that drops live handles when pickled", and a
  test that needed h5py to prove that would be testing the wrong thing.
"""

from __future__ import annotations

import dataclasses
import multiprocessing
import os
import pickle
import threading
from multiprocessing.context import BaseContext

import pytest

from molhub.conveyor.backpressure import (
    ByteBoundedQueue,
    PrepareWorkers,
    QueueError,
    QueueOversized,
    QueueTimeout,
)

CAPACITY = 2_000_000
HALF = 1_000_000

_FORK = pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(),
    reason="this platform cannot fork; the spawn default is asserted without spawning",
)


def _full() -> ByteBoundedQueue:
    """A queue holding exactly its capacity, in two reservations."""
    queue = ByteBoundedQueue(capacity_bytes=CAPACITY)
    queue.reserve("a", nbytes=HALF)
    queue.reserve("b", nbytes=HALF)
    return queue


def _context_of(pool: PrepareWorkers) -> BaseContext:
    """The multiprocessing context *pool* will run its workers in.

    Read through ``getattr`` so this file pins ac-009's *value* — the default is
    spawn — without also pinning which of the two obvious attribute names the
    pool publishes it under.
    """
    context = getattr(pool, "mp_context", None) or getattr(pool, "context", None)
    assert context is not None, "PrepareWorkers must publish the context it will run workers in"
    return context


@dataclasses.dataclass(frozen=True)
class RunOutcome:
    """What :class:`FakeRunner` returns — picklable, so it can cross back.

    Attributes:
        job: The job that produced it.
        handle: The per-pid handle string that was open when it ran.
        pid: The process that ran it.
    """

    job: str
    handle: str
    pid: int


class FakeRunner:
    """A ``JobRunner`` with ``THEMolCollection``'s per-pid handle discipline.

    ``__getstate__`` drops the handle *and* the pid it was opened in
    (``src/molhub/dataset/themol.py:149-161``), and :meth:`run` re-opens when
    ``os.getpid()`` differs. An open HDF5 handle that crossed a process boundary
    intact is the corruption path the spawn default exists to avoid; a fake that
    did not model it would let the pool land without the contract.

    Args:
        label: Stands in for the shard path a real runner would open.
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._handle: str | None = None
        self._pid: int | None = None
        self._opens = 0

    def __getstate__(self) -> dict[str, object]:
        state = dict(self.__dict__)
        state["_handle"] = None
        state["_pid"] = None
        return state

    @property
    def opens(self) -> int:
        """How many times a handle has been opened in this process."""
        return self._opens

    def _open(self) -> str:
        pid = os.getpid()
        if self._handle is None or self._pid != pid:
            self._handle = f"{self._label}@{pid}"
            self._pid = pid
            self._opens += 1
        return self._handle

    def run(self, job: str) -> RunOutcome:
        """Run one job against this process's handle."""
        return RunOutcome(job=job, handle=self._open(), pid=os.getpid())


class TestByteBoundedQueue:
    """Bounded in bytes, freed by deletion — never by dequeue."""

    def test_a_reservation_holds_its_bytes(self):
        queue = ByteBoundedQueue(capacity_bytes=CAPACITY)
        queue.reserve("a", nbytes=HALF)
        assert queue.held_bytes == HALF

    def test_reservations_accumulate(self):
        assert _full().held_bytes == CAPACITY

    def test_the_pinned_held_bytes_trace(self):
        """reserve, reserve, refused probe, take, release, reserve — in bytes."""
        queue = ByteBoundedQueue(capacity_bytes=CAPACITY)
        trace: list[int] = []

        queue.reserve("a", nbytes=HALF)
        trace.append(queue.held_bytes)
        queue.reserve("b", nbytes=HALF)
        trace.append(queue.held_bytes)
        with pytest.raises(QueueTimeout):
            queue.reserve("c", nbytes=HALF, timeout=0)
        trace.append(queue.held_bytes)
        queue.take(timeout=0)
        trace.append(queue.held_bytes)
        queue.release("a")
        trace.append(queue.held_bytes)
        queue.reserve("c", nbytes=HALF)
        trace.append(queue.held_bytes)

        assert tuple(trace) == (HALF, CAPACITY, CAPACITY, CAPACITY, HALF, CAPACITY)

    def test_take_hands_the_item_and_its_weight_downstream(self):
        assert _full().take(timeout=0) == ("a", HALF)

    def test_take_is_first_in_first_out(self):
        queue = _full()
        queue.take(timeout=0)
        assert queue.take(timeout=0) == ("b", HALF)

    def test_take_does_not_free_bytes(self):
        """The bytes are still on disk; freeing here would exceed the budget by a depth."""
        queue = _full()
        queue.take(timeout=0)
        assert queue.held_bytes == CAPACITY

    def test_release_frees_the_bytes(self):
        queue = _full()
        queue.release("a")
        assert queue.held_bytes == HALF

    def test_a_full_queue_refuses_a_zero_timeout_probe(self):
        with pytest.raises(QueueTimeout):
            _full().reserve("c", nbytes=HALF, timeout=0)

    def test_a_refused_probe_holds_no_bytes(self):
        queue = _full()
        with pytest.raises(QueueTimeout):
            queue.reserve("c", nbytes=HALF, timeout=0)
        assert queue.held_bytes == CAPACITY

    def test_the_probe_is_admitted_after_a_release(self):
        queue = _full()
        queue.release("a")
        queue.reserve("c", nbytes=HALF, timeout=0)
        assert queue.held_bytes == CAPACITY

    def test_a_reservation_larger_than_the_capacity_is_refused(self):
        """A reservation that can never be satisfied is a deadlock, not backpressure."""
        queue = ByteBoundedQueue(capacity_bytes=CAPACITY)
        with pytest.raises(QueueOversized):
            queue.reserve("huge", nbytes=CAPACITY + 1, timeout=0)

    def test_an_oversized_reservation_is_refused_before_the_wait(self):
        """Full or empty makes no difference: the size check precedes admission."""
        with pytest.raises(QueueOversized):
            _full().reserve("huge", nbytes=3_000_000, timeout=0)

    def test_an_oversized_reservation_holds_no_bytes(self):
        queue = ByteBoundedQueue(capacity_bytes=CAPACITY)
        with pytest.raises(QueueOversized):
            queue.reserve("huge", nbytes=3_000_000, timeout=0)
        assert queue.held_bytes == 0
        assert queue.pending == 0

    def test_capacity_bytes_reads_back_what_was_configured(self):
        assert ByteBoundedQueue(capacity_bytes=CAPACITY).capacity_bytes == CAPACITY

    def test_pending_counts_the_items_waiting_to_be_taken(self):
        assert _full().pending == 2

    def test_a_taken_item_is_no_longer_pending(self):
        queue = _full()
        queue.take(timeout=0)
        assert queue.pending == 1

    def test_an_empty_queue_has_nothing_to_take(self):
        with pytest.raises(QueueTimeout):
            ByteBoundedQueue(capacity_bytes=CAPACITY).take(timeout=0)

    def test_the_error_family_is_one_queue_error(self):
        assert issubclass(QueueTimeout, QueueError)
        assert issubclass(QueueOversized, QueueError)

    def test_a_blocked_reserve_wakes_when_the_bytes_are_released(self):
        """ac-008: the one threaded test. Event handshake in, bounded join out."""
        queue = ByteBoundedQueue(capacity_bytes=CAPACITY)
        queue.reserve("a", nbytes=CAPACITY)
        about_to_wait = threading.Event()
        admitted: list[str] = []

        def waiter() -> None:
            about_to_wait.set()
            queue.reserve("b", nbytes=HALF, timeout=5)
            admitted.append("b")

        thread = threading.Thread(target=waiter, name="reserve-waiter")
        thread.start()
        try:
            assert about_to_wait.wait(timeout=5)
            queue.release("a")
            thread.join(timeout=5)
        finally:
            if thread.is_alive():  # pragma: no cover - only on a failed wake
                thread.join(timeout=5)

        assert not thread.is_alive()
        assert admitted == ["b"]
        assert queue.held_bytes == HALF


class TestPrepareWorkers:
    """Processes, because prepare is CPU-bound behind the GIL."""

    def test_the_default_context_is_spawn(self):
        """Forking a process holding an open HDF5 file is a known corruption path."""
        pool = PrepareWorkers(FakeRunner("shard-000"), workers=1)
        try:
            assert _context_of(pool).get_start_method() == "spawn"
        finally:
            pool.close()

    def test_an_injected_context_is_used_verbatim(self):
        context = multiprocessing.get_context("spawn")
        pool = PrepareWorkers(FakeRunner("shard-000"), workers=1, mp_context=context)
        try:
            assert _context_of(pool) is context
        finally:
            pool.close()

    @_FORK
    def test_a_submitted_job_runs_in_a_worker_process(self):
        context = multiprocessing.get_context("fork")
        with PrepareWorkers(FakeRunner("shard-000"), workers=1, mp_context=context) as pool:
            pool.submit("job-a")
            outcome = pool.collect(timeout=30)
        assert outcome.job == "job-a"
        assert outcome.pid != os.getpid()

    @_FORK
    def test_the_worker_opened_its_own_handle(self):
        """The handle names the worker's pid, so it was re-opened after the crossing."""
        context = multiprocessing.get_context("fork")
        with PrepareWorkers(FakeRunner("shard-000"), workers=1, mp_context=context) as pool:
            pool.submit("job-a")
            outcome = pool.collect(timeout=30)
        assert outcome.handle == f"shard-000@{outcome.pid}"

    @_FORK
    def test_every_submitted_job_is_collected(self):
        context = multiprocessing.get_context("fork")
        with PrepareWorkers(FakeRunner("shard-000"), workers=2, mp_context=context) as pool:
            pool.submit("job-a")
            pool.submit("job-b")
            outcomes = [pool.collect(timeout=30), pool.collect(timeout=30)]
        assert sorted(outcome.job for outcome in outcomes) == ["job-a", "job-b"]

    @_FORK
    def test_the_context_manager_yields_the_pool(self):
        context = multiprocessing.get_context("fork")
        with PrepareWorkers(FakeRunner("shard-000"), workers=1, mp_context=context) as pool:
            assert isinstance(pool, PrepareWorkers)

    @_FORK
    def test_close_is_idempotent(self):
        """The context manager closes on exit; a caller's own ``close`` must not double-fail."""
        context = multiprocessing.get_context("fork")
        with PrepareWorkers(FakeRunner("shard-000"), workers=1, mp_context=context) as pool:
            pool.close()
        pool.close()

    def test_the_runner_drops_its_handle_when_it_is_pickled(self):
        """The runner crosses by pickling, so a live handle must not cross with it."""
        runner = FakeRunner("shard-000")
        runner.run("job-a")
        revived = pickle.loads(pickle.dumps(runner))
        assert revived.__dict__["_handle"] is None
        assert revived.__dict__["_pid"] is None

    def test_the_runner_reopens_its_handle_when_the_pid_changes(self, monkeypatch):
        runner = FakeRunner("shard-000")
        runner.run("job-a")
        monkeypatch.setattr(os, "getpid", lambda: 999_999)
        assert runner.run("job-b").handle == "shard-000@999999"

    def test_the_runner_opens_one_handle_per_process(self):
        runner = FakeRunner("shard-000")
        runner.run("job-a")
        runner.run("job-b")
        assert runner.opens == 1
