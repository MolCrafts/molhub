"""Neighbour-list delegation — molhub asks molnex, and never answers itself.

The cutoff graph (``edge_index`` / ``edge_diff`` / ``edge_dist``) is a physics
contract: which pairs count, how periodic images are folded in, whether the
list is bidirectional, and which way an edge displacement points. MolNex owns
that contract in ``molix.neighbor.NeighborList``, together with the kernel-output
normalisation it implies — the periodic-image handling, the padding strip, the
symmetry expansion and the edge-sign convention. A second implementation over
here would not be a copy for long, and the two would then disagree about the
same molecule while both looking right in isolation.

So this module holds no neighbour algorithm at all. It holds a delegate: one
seam where the wrapped list is injected (a stand-in for tests, a list
configured for periodic systems, a future replacement), and otherwise a
straight forward of the call, the result, and the cache identity.

``molix`` is imported inside the method that needs it. MolNex is an optional
peer of MolHub — only this module wants it, and only when it runs — so a
module-level import would make :mod:`molhub.dataset` unimportable in MolHub's
own environment, where torch is not installed.

Edge convention (molnex): ``edge_index[:, 0]`` is the source, column 1 the
target, and the displacement runs source → target.

Usage::

    from molhub.dataset.neighbor import NeighborDelegate

    delegate = NeighborDelegate(cutoff=5.0)
    sample = delegate.execute({"Z": z, "pos": pos})
    sample["edge_index"], sample["edge_diff"], sample["edge_dist"]
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["NeighborListSeam", "NeighborDelegate"]


class NeighborListSeam(Protocol):
    """What :class:`NeighborDelegate` requires of the list it wraps.

    ``molix.neighbor.NeighborList`` satisfies this by shape and declares nothing;
    so does any stand-in a caller injects. Naming the molnex class at this seam
    instead would make every substitute a subclass problem — and would drag a
    torch import into a package that does not need one.
    """

    @property
    def task_id(self) -> str:
        """Cache identity of the graph this list builds."""
        ...

    def execute(self, data: dict[str, object]) -> dict[str, object]:
        """Return *data* with the cutoff graph attached."""
        ...


class NeighborDelegate:
    """Builds a sample's cutoff graph by asking ``molix.neighbor.NeighborList``.

    Args:
        cutoff: Cutoff radius in Å for the list this delegate builds.
        symmetry: ``True`` (default) for a full bidirectional list, ``False``
            for upper-triangle half pairs only. The two produce different edge
            tensors and therefore different :attr:`task_id` values.
        neighbor_list: Use this list instead of building one. The seam for a
            test stand-in, or for a list configured beyond what *cutoff* and
            *symmetry* reach (periodic boundaries, a larger pair buffer) —
            construct that list yourself and hand it over. When given,
            *cutoff* and *symmetry* describe it rather than configure it.
    """

    def __init__(
        self,
        cutoff: float = 5.0,
        *,
        symmetry: bool = True,
        neighbor_list: NeighborListSeam | None = None,
    ) -> None:
        self.cutoff = float(cutoff)
        self.symmetry = symmetry
        self._neighbor_list = neighbor_list

    @property
    def neighbor_list(self) -> NeighborListSeam:
        """The wrapped list, built on first use when none was injected.

        Raises:
            ImportError: molnex is not importable in this environment.
        """
        if self._neighbor_list is None:
            try:
                from molix.neighbor import NeighborList
            except ImportError as error:
                raise ImportError(
                    "molhub.dataset.neighbor delegates to molix.neighbor.NeighborList, "
                    "which is not importable here. Install molnex alongside molhub, "
                    "or inject a list of your own via neighbor_list=."
                ) from error
            self._neighbor_list = NeighborList(cutoff=self.cutoff, symmetry=self.symmetry)
        return self._neighbor_list

    @property
    def task_id(self) -> str:
        """The wrapped list's cache identity, verbatim.

        Delegated for the same reason the computation is: if this string were
        composed here, a change to how molnex builds the graph would leave two
        caches keyed identically and holding different edges.
        """
        return self.neighbor_list.task_id

    def execute(self, data: dict[str, object]) -> dict[str, object]:
        """Return what the wrapped list returns for *data*, unchanged.

        Args:
            data: One sample, with the positions the wrapped list reads.

        Returns:
            The wrapped list's own result object — the edge tensors are its
            tensors, not copies or re-derivations of them.
        """
        return self.neighbor_list.execute(data)

    def __call__(self, data: dict[str, object]) -> dict[str, object]:
        """Alias of :meth:`execute`."""
        return self.execute(data)
