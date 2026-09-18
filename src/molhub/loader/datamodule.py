"""DataModule for molhub datasets.

Packing sizes come from ``train.get_distrib(field).raw`` (a live Frame
scan). Snapshot ``dataset.cache`` is disabled. Collation stays behind
molix ``DataModuleProtocol``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

__all__ = ["DataModule"]


class DataModule:
    """DataModuleProtocol over molhub datasets; packing reads ``get_distrib``.

    Construction is ``DataModule(train, val, *, field="graph.natoms", ...)``.
    When ``max_atoms_per_batch`` is set, per-row sizes are
    ``train.get_distrib(field).raw``.

    Args:
        train: Map-style train dataset. Packing requires ``get_distrib``.
        val: Map-style validation dataset.
        batch_tasks: Post-collate tasks forwarded to molix.
        batch_size: Samples per batch when no atom budget is set.
        max_atoms_per_batch: Optional per-batch atom budget.
        max_edges_per_batch: Optional per-batch pair budget, forwarded to molix
            as ``max_pairs_per_batch`` (molnex renamed the cutoff-pair
            vocabulary; this wrapper's own name is unchanged for now).
        field: Frame field packed under ``max_atoms_per_batch``. Default
            ``graph.natoms``.
        **loader_kwargs: Forwarded to molix ``DataModule``.
    """

    def __init__(
        self,
        train: Any,
        val: Any,
        *,
        batch_tasks: Sequence[Any] | None = None,
        batch_size: int = 32,
        max_atoms_per_batch: int | None = None,
        max_edges_per_batch: int | None = None,
        field: str = "graph.natoms",
        **loader_kwargs: Any,
    ) -> None:
        from molix.data import DataModule as MolixDataModule

        if "cache" in loader_kwargs:
            raise TypeError("DataModule no longer takes cache=; packing uses get_distrib(field)")
        atom_counts = loader_kwargs.pop("atom_counts", None)
        if max_atoms_per_batch is not None and atom_counts is None:
            import numpy as np
            import torch

            vector = np.asarray(train.get_distrib(field).raw)
            atom_counts = torch.as_tensor(vector, dtype=torch.long)
        inner = MolixDataModule(
            train,
            val,
            batch_tasks=batch_tasks,
            batch_size=batch_size,
            max_atoms_per_batch=max_atoms_per_batch,
            max_pairs_per_batch=max_edges_per_batch,
            atom_counts=atom_counts,
            **loader_kwargs,
        )
        self._inner = inner
        self.train_dataset = train
        self.val_dataset = val
        self.batch_tasks = inner.batch_tasks
        self.batch_size = inner.batch_size
        self.num_workers = inner.num_workers
        self.pin_memory = inner.pin_memory
        self.prefetch_factor = inner.prefetch_factor
        self.multiprocessing_context = inner.multiprocessing_context
        self.seed = inner.seed
        self.field = field

    def setup(self, stage: str = "fit") -> None:
        """Prepare datasets/samplers for *stage*; forwarded to molix."""
        self._inner.setup(stage)

    def train_dataloader(self) -> Iterable:
        """Training loader; packing already consumed ``get_distrib(field)``."""
        return self._inner.train_dataloader()

    def val_dataloader(self) -> Iterable:
        """Validation loader."""
        return self._inner.val_dataloader()

    def on_epoch_start(self, epoch: int) -> None:
        """Reseed shuffling for *epoch*."""
        self._inner.on_epoch_start(epoch)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
