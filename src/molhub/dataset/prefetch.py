"""Generic batched fetch for map-style datasets.

Torch's map fetcher calls ``dataset.__getitems__`` when the dataset has one
(``torch.utils.data._utils.fetch._MapDatasetFetcher``). That is the whole
integration: a dataset implements :meth:`Prefetch.__getitems__` and the
loader's ``prefetch_factor`` keeps overlapping the next batch. Nothing here
knows which file format the dataset reads, or whether it keeps a cache.

``stage`` does the IO and returns plain bytes or numpy, which is safe to hand
across threads. ``realize`` builds molpy frames on the calling thread. A
frame is a molrs object and has to stay on the thread that made it. A dataset
that stores decoded samples does that inside its own ``stage`` and ``realize``.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

__all__ = ["Prefetch", "getitems"]


def getitems(dataset: Any, indices: Sequence[Any], *, workers: int = 4) -> list[Any]:
    """Read *indices*, staging on a pool and realizing on this thread.

    ``workers <= 1``, a single index, or a dataset without ``stage`` and
    ``realize`` reads each index through ``__getitem__``. The pool is opened
    and shut inside the call, so its threads do not outlive the batch.

    Args:
        dataset: A map-style dataset.
        indices: The batch. Each entry is passed through ``int``.
        workers: How many threads stage at once.

    Returns:
        One sample per index, in the order given.
    """
    chosen = [int(index) for index in indices]
    stage = getattr(dataset, "stage", None)
    realize = getattr(dataset, "realize", None)
    if workers <= 1 or len(chosen) <= 1 or not callable(stage) or not callable(realize):
        return [dataset[index] for index in chosen]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        staged = list(pool.map(stage, chosen))
    return [realize(item) for item in staged]


class Prefetch:
    """``__getitems__`` via :func:`getitems`.

    Attributes:
        prefetch_workers: Threads used to stage one batch. ``1`` stays serial.
    """

    prefetch_workers = 4

    def __getitems__(self, indices: Sequence[Any]) -> list[Any]:
        return getitems(self, indices, workers=int(self.prefetch_workers))
