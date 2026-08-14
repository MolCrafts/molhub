"""Byte-weighted admission control between stages, and the workers that prepare.

Two collaborators that only make sense together: a handoff that is bounded in
**bytes** rather than in items, and a pool of worker **processes** that consume
it. Both exist because the conveyor's binding constraint is physical — local
disk and CPU cores — and a queue that counted items or a pool that spawned
threads would give up exactly the guarantee the byte budget buys.

**Bounded in bytes, freed by deletion.** Four 20 GB THEMol shards are 80 GB, so
``maxsize=4`` says nothing about residency (I4). :class:`ByteBoundedQueue`
weights every item with its declared size and — the part that makes it not
:class:`queue.Queue` — :meth:`ByteBoundedQueue.take` does **not** free those
bytes. The bytes are still on disk when the downstream stage picks the item up;
freeing them at dequeue would let residency exceed the budget by a full pipeline
depth. Bytes are freed by :meth:`ByteBoundedQueue.release`, which the caller
invokes once the file is actually gone. A reservation larger than the capacity
is refused immediately rather than waited on: a request that can never be
satisfied is a deadlock, not backpressure.

**Processes, not threads.** The prepare stage decodes records and builds numeric
columns; it is CPU-bound, so under the GIL a thread pool would serialize exactly
the work the rate condition needs ``W ≥ c_prep · r_train`` cores for.
:class:`PrepareWorkers` therefore runs its runner in worker processes.

**Spawn is the default.** The runner crosses the process boundary by pickling,
and forking a process that holds an open HDF5 handle or a live torch runtime is
a known corruption path: the child inherits a file descriptor and an internal
state it never opened. Spawn starts clean, which is why it is the default here
even though it costs an interpreter start, and why the runner contract is
``THEMolCollection``'s (``src/molhub/dataset/themol.py:149-161``): drop live
handles and the pid they were opened in from ``__getstate__``, re-open when
:func:`os.getpid` differs. A caller who has measured that fork is safe for its
runner can inject ``multiprocessing.get_context("fork")``; the default never
guesses that on the caller's behalf.

Workers are started on the first :meth:`PrepareWorkers.submit`, not at
construction, so building a pool to read its configuration costs no process.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-04-residency.md`` §§ 4-5.
"""

from __future__ import annotations

import multiprocessing
import queue as queue_module
import threading
from collections import deque
from multiprocessing.context import BaseContext
from typing import Any, Protocol, runtime_checkable

from molhub.conveyor.block import ConveyorError

__all__ = [
    "QueueError",
    "QueueTimeout",
    "QueueOversized",
    "DuplicateReservation",
    "UnknownReservation",
    "ByteBoundedQueue",
    "JobRunner",
    "WorkerRefusal",
    "PrepareWorkers",
]

# How long `close` waits for a worker to notice its stop token before it stops
# being polite about it. Bounded so a wedged worker cannot hang an interpreter
# exit; the pool's processes are daemons for the same reason.
_JOIN_SECONDS = 10.0


class QueueError(ConveyorError):
    """A byte-bounded handoff cannot do what was asked of it."""


class QueueTimeout(QueueError):
    """The wait ran out: capacity did not free, or nothing arrived to take.

    ``timeout=0`` makes this the single-threaded probe the acceptance criteria
    pin — full raises, freed admits — with no sleeping and no wall clock.
    """


class QueueOversized(QueueError):
    """A reservation larger than the whole capacity, refused without waiting.

    Waiting would be waiting forever: no sequence of releases can make room for
    an item that does not fit in an empty queue. That is a deadlock, and naming
    it here is the difference between a stalled pipeline and a diagnosable one.
    """


class DuplicateReservation(QueueError):
    """This item already holds bytes in this queue.

    An item is its own handle — a block key, a shard path — and
    :meth:`ByteBoundedQueue.release` frees bytes by that handle. Admitting the
    same handle twice would make one release free the wrong reservation, so the
    second one is refused rather than silently mis-accounted.
    """


class UnknownReservation(QueueError):
    """This queue holds no bytes for that item, so it has none to free."""


class WorkerRefusal(ConveyorError):
    """The runner raised inside a worker process.

    The original exception is quoted as text: a traceback cannot cross a process
    boundary, and re-raising a half-reconstructed exception would be a worse lie
    than a faithful quote. A worker that raised has produced no outcome, so the
    caller's :meth:`PrepareWorkers.collect` sees this instead of hanging until
    its timeout.
    """


class ByteBoundedQueue:
    """A FIFO handoff bounded by the bytes its items occupy on disk.

    Construct with a capacity, reserve bytes as items are produced, take items
    downstream, release bytes once the files are deleted. The four verbs are
    separate because "handed on" and "deleted" are different events, and
    conflating them is what makes a residency budget leak.

    Args:
        capacity_bytes: The most bytes this queue may hold reserved at once. The
            name is spelled out because a bare number that could be a count or a
            byte size is precisely the confusion the byte budget exists to
            remove.

    Raises:
        ValueError: If *capacity_bytes* is not positive.
    """

    def __init__(self, *, capacity_bytes: int) -> None:
        if capacity_bytes <= 0:
            raise ValueError(
                f"capacity_bytes must be a positive number of bytes; got {capacity_bytes}."
            )
        self._capacity_bytes = capacity_bytes
        self._held_bytes = 0
        self._weights: dict[str, int] = {}
        self._waiting: deque[tuple[str, int]] = deque()
        self._condition = threading.Condition()

    @property
    def capacity_bytes(self) -> int:
        """The most bytes this queue may hold reserved at once."""
        return self._capacity_bytes

    @property
    def held_bytes(self) -> int:
        """Bytes currently reserved — taken or not, until they are released."""
        with self._condition:
            return self._held_bytes

    @property
    def pending(self) -> int:
        """How many items have been reserved and not yet taken."""
        with self._condition:
            return len(self._waiting)

    def reserve(self, item: str, *, nbytes: int, timeout: float | None = None) -> None:
        """Hold *nbytes* bytes for *item* and put it in line, waiting if needed.

        Args:
            item: The handle the downstream stage will receive and the one
                :meth:`release` frees bytes by.
            nbytes: The bytes *item* occupies on disk.
            timeout: Seconds to wait for room. ``None`` waits indefinitely;
                ``0`` polls once, which is the deterministic probe.

        Raises:
            ValueError: If *nbytes* is not positive.
            QueueOversized: If *nbytes* exceeds :attr:`capacity_bytes`. Raised
                immediately, before any wait.
            DuplicateReservation: If *item* already holds bytes here.
            QueueTimeout: If the room did not free within *timeout*; no bytes
                are held.
        """
        if nbytes <= 0:
            raise ValueError(f"nbytes must be a positive number of bytes; got {nbytes}.")
        if nbytes > self._capacity_bytes:
            raise QueueOversized(
                f"{item} declares {nbytes} B but this queue holds at most "
                f"{self._capacity_bytes} B. No sequence of releases could admit it, so "
                "waiting would be waiting forever."
            )
        with self._condition:
            if item in self._weights:
                raise DuplicateReservation(
                    f"{item} already holds {self._weights[item]} B here. One release frees "
                    "one handle's bytes, so the same handle may not be admitted twice."
                )
            admitted = self._condition.wait_for(
                lambda: self._held_bytes + nbytes <= self._capacity_bytes, timeout
            )
            if not admitted:
                raise QueueTimeout(
                    f"{item} waited {timeout} s for {nbytes} B: this queue holds "
                    f"{self._held_bytes} B of {self._capacity_bytes} B. Bytes free when a "
                    "downstream stage deletes what it consumed, not when it dequeues."
                )
            self._held_bytes += nbytes
            self._weights[item] = nbytes
            self._waiting.append((item, nbytes))

    def take(self, timeout: float | None = None) -> tuple[str, int]:
        """Hand the next item downstream, without freeing its bytes.

        Args:
            timeout: Seconds to wait for an item. ``None`` waits indefinitely;
                ``0`` polls once.

        Returns:
            The item and the bytes it is charged, oldest reservation first.

        Raises:
            QueueTimeout: If nothing arrived within *timeout*.
        """
        with self._condition:
            arrived = self._condition.wait_for(lambda: bool(self._waiting), timeout)
            if not arrived:
                raise QueueTimeout(
                    f"Nothing to take after {timeout} s; this queue holds {self._held_bytes} B "
                    f"of {self._capacity_bytes} B across {len(self._waiting)} item(s)."
                )
            return self._waiting.popleft()

    def release(self, item: str) -> int:
        """Free the bytes *item* was holding, because its file is gone.

        Position in the take order and bytes on disk are independent facts:
        releasing frees bytes and wakes whoever is waiting for room; it does not
        cancel a handoff that has not happened yet.

        Args:
            item: The handle whose bytes were deleted.

        Returns:
            The bytes freed.

        Raises:
            UnknownReservation: If this queue holds no bytes for *item*.
        """
        with self._condition:
            nbytes = self._weights.pop(item, None)
            if nbytes is None:
                raise UnknownReservation(
                    f"This queue holds no bytes for {item}; it was never reserved here, or "
                    "its bytes were freed already."
                )
            self._held_bytes -= nbytes
            self._condition.notify_all()
            return nbytes


@runtime_checkable
class JobRunner(Protocol):
    """The one verb a worker process needs from whatever it is running.

    A required-side view: the pool defines no job type and no outcome type, so
    ``-03``'s :class:`~molhub.conveyor.encoder.THEMolUnitEncoder` and a unit
    test's fake satisfy it equally. The implementation must be picklable and
    must drop live handles in ``__getstate__``, re-opening them per pid — see
    the module docstring.
    """

    def run(self, job: Any) -> Any:
        """Run one job in this process and return its outcome."""
        ...


class _Stop:
    """The token that tells one worker to finish; picklable, unlike a sentinel.

    Compared with :func:`isinstance`, not with ``is``: identity does not survive
    the crossing, and a magic string would be a state-shaped literal in a
    package that has exactly four legal ones.
    """


class _Refusal:
    """A worker's report that the runner raised, carried back as text.

    Attributes:
        text: ``repr`` of the exception, quoted verbatim into
            :class:`WorkerRefusal` by the collecting process.
    """

    def __init__(self, text: str) -> None:
        self.text = text


def _serve(runner: JobRunner, jobs: Any, outcomes: Any) -> None:
    """Run jobs from *jobs* until a stop token arrives, reporting into *outcomes*.

    A module-level function because a spawned child imports this module and
    looks the target up by name; a closure or a bound method would not survive
    the crossing.

    Args:
        runner: The unpickled runner, whose handles this process re-opens.
        jobs: The job queue the pool feeds.
        outcomes: The queue outcomes are reported on.
    """
    while True:
        job = jobs.get()
        if isinstance(job, _Stop):
            return
        try:
            outcome = runner.run(job)
        except Exception as error:  # reported, never swallowed: see _Refusal
            outcomes.put(_Refusal(repr(error)))
        else:
            outcomes.put(outcome)


class PrepareWorkers:
    """A pool of worker processes running one runner's jobs.

    Submit and collect are separate verbs and there is no ``run_all``: composing
    the loop — how many jobs are in flight, when to stop — is the caller's job,
    and it is the caller who holds the byte budget that decides it.

    Args:
        runner: Anything satisfying :class:`JobRunner`. It is pickled once per
            worker, so it must drop live handles in ``__getstate__``.
        workers: How many worker processes to run.
        mp_context: The multiprocessing context to start them in. Defaults to
            ``spawn`` — see the module docstring for why a fork is the caller's
            explicit decision, never this class's default.

    Raises:
        ValueError: If *workers* is not positive.
    """

    def __init__(
        self,
        runner: JobRunner,
        *,
        workers: int,
        mp_context: BaseContext | None = None,
    ) -> None:
        if workers <= 0:
            raise ValueError(f"workers must be a positive process count; got {workers}.")
        self._runner = runner
        self._workers = workers
        self._mp_context = mp_context or multiprocessing.get_context("spawn")
        self._jobs: Any = None
        self._outcomes: Any = None
        self._processes: tuple[Any, ...] = ()
        self._closed = False

    @property
    def mp_context(self) -> BaseContext:
        """The multiprocessing context this pool starts its workers in."""
        return self._mp_context

    @property
    def workers(self) -> int:
        """How many worker processes this pool runs."""
        return self._workers

    def submit(self, job: Any) -> None:
        """Hand *job* to the pool, starting the workers on the first call.

        Args:
            job: Whatever the runner's ``run`` accepts. It is pickled to reach a
                worker, so it must be picklable.

        Raises:
            RuntimeError: If this pool has been closed.
        """
        if self._closed:
            raise RuntimeError("This pool is closed; build another one to run more jobs.")
        self._start()
        self._jobs.put(job)

    def collect(self, *, timeout: float) -> Any:
        """Take one outcome, waiting up to *timeout* seconds for it.

        One outcome per call, in whatever order the workers finished: with more
        than one worker the completion order is not the submission order, and
        pretending otherwise would be a queue the pool does not have.

        Args:
            timeout: Seconds to wait.

        Returns:
            Whatever the runner returned for one submitted job.

        Raises:
            QueueTimeout: If no outcome arrived within *timeout*.
            WorkerRefusal: If the runner raised for that job.
        """
        if self._outcomes is None:
            raise QueueTimeout(
                "This pool has nothing in flight: no job has been submitted, or it was closed."
            )
        try:
            outcome = self._outcomes.get(timeout=timeout)
        except queue_module.Empty as error:
            raise QueueTimeout(
                f"No outcome arrived within {timeout} s from {self._workers} worker(s)."
            ) from error
        if isinstance(outcome, _Refusal):
            raise WorkerRefusal(
                f"A worker's runner raised {outcome.text}. The job produced no outcome; "
                "a traceback cannot cross a process boundary, so this is the quote."
            )
        return outcome

    def close(self) -> None:
        """Stop the workers and drop the queues. Idempotent.

        Each worker is sent one stop token and joined; one that ignores it
        within the pool's bounded wait is terminated, because a wedged worker
        must not outlive the pool that owns it.
        """
        if self._closed:
            return
        self._closed = True
        for _ in self._processes:
            self._jobs.put(_Stop())
        for process in self._processes:
            process.join(timeout=_JOIN_SECONDS)
            if process.is_alive():
                process.terminate()
                process.join(timeout=_JOIN_SECONDS)
        self._processes = ()
        for handoff in (self._jobs, self._outcomes):
            if handoff is not None:
                # The workers are gone, so whatever is still buffered has no
                # reader; waiting for the feeder to flush it into a pipe nobody
                # drains is how a teardown becomes a hang.
                handoff.cancel_join_thread()
                handoff.close()
        self._jobs = None
        self._outcomes = None

    def __enter__(self) -> PrepareWorkers:
        """Return this pool, so ``with PrepareWorkers(...) as pool`` reads plainly."""
        return self

    def __exit__(self, *exception: object) -> None:
        """Close the pool, whatever the block did."""
        self.close()

    def _start(self) -> None:
        """Create the queues and start the workers, once."""
        if self._processes:
            return
        self._jobs = self._mp_context.Queue()
        self._outcomes = self._mp_context.Queue()
        # `get_context()` on a context returns that same context (and resolves
        # the default one when a caller passed it). It is spelled out because
        # the process class is declared on the concrete contexts — spawn, fork,
        # forkserver — rather than on the base this class honestly accepts.
        spawner = self._mp_context.get_context()
        self._processes = tuple(
            spawner.Process(
                target=_serve,
                args=(self._runner, self._jobs, self._outcomes),
                daemon=True,
            )
            for _ in range(self._workers)
        )
        for process in self._processes:
            process.start()
