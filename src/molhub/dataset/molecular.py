"""Force-field / multi-conformer molecular dataset contract helpers.

Canonical boundary units match Espaloma parity (Å, kcal/mol, kcal/mol/Å, rad).
Molecule-level split schemes keep all conformers of one molecule in a single
partition so no held-out molecule leaks into training.

References:
    Wang, Fass, Greene, et al. "End-to-end differentiable molecular mechanics
    force field construction." arXiv:2010.01196; *Chem. Sci.* (2022).
    DOI: 10.1039/D2SC02739A.
"""

from __future__ import annotations

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from molpy import Frame

from molhub.dataset.meta import Targets
from molhub.dataset.protocol import MapDataset, SubsetDataset

__all__ = [
    "ANGLE",
    "CONFORMER_ID",
    "DISTANCE",
    "ENERGY",
    "FORCE",
    "KNOWN_SPLIT_SCHEMES",
    "MOLECULE_ID",
    "MolecularFrame",
    "MolecularUnits",
    "MoleculeSplit",
]

# ---------------------------------------------------------------------------
# Identity meta keys
# ---------------------------------------------------------------------------

MOLECULE_ID = "molecule_id"
"""Graph-level meta key for the stable molecule identity shared by conformers."""

CONFORMER_ID = "conformer_id"
"""Optional graph-level meta key distinguishing conformers of one molecule."""

# Topology column names (atom / bond blocks)
ATOM_ELEMENT = "element"
ATOM_NUMBER = "number"
ATOM_FORMAL_CHARGE = "formal_charge"
ATOM_AROMATIC = "aromatic"
BOND_ATOMI = "atomi"
BOND_ATOMJ = "atomj"
BOND_ORDER = "order"

KNOWN_SPLIT_SCHEMES: frozenset[str] = frozenset({"espaloma-original", "molhub-random-molecule"})
"""First-class molecule-level split scheme names for MM validation."""


class MolecularUnits:
    """Canonical unit tokens at the force-field dataset boundary.

    Attributes:
        DISTANCE: Positions / bond lengths in angstrom.
        ENERGY: Energies in kcal/mol (Espaloma parity).
        FORCE: Forces in kcal/mol/Å.
        ANGLE: Stored angle targets in radian (convert at I/O if upstream is deg).
    """

    DISTANCE: str = "angstrom"
    ENERGY: str = "kcal/mol"
    FORCE: str = "kcal_per_mol_angstrom"
    ANGLE: str = "radian"

    @classmethod
    def describe(cls) -> Mapping[str, str]:
        """Return a mapping of quantity name → unit token."""
        return {
            "distance": cls.DISTANCE,
            "energy": cls.ENERGY,
            "force": cls.FORCE,
            "angle": cls.ANGLE,
        }


# Module-level aliases matching the public re-export contract.
DISTANCE = MolecularUnits.DISTANCE
ENERGY = MolecularUnits.ENERGY
FORCE = MolecularUnits.FORCE
ANGLE = MolecularUnits.ANGLE


class MolecularFrame:
    """Thin view over a molpy :class:`~molpy.Frame` for FF dataset samples.

    Every sample remains a plain :class:`~molpy.Frame`. This helper only
    reads identity meta written through :class:`~molhub.dataset.Targets` and
    checks covalent connectivity columns.

    Args:
        frame: The underlying sample frame.
    """

    def __init__(self, frame: Frame) -> None:
        self._frame = frame

    @property
    def frame(self) -> Frame:
        """The wrapped :class:`~molpy.Frame`."""
        return self._frame

    @property
    def molecule_id(self) -> str | None:
        """Molecule identity from graph meta, or ``None`` if absent."""
        targets = Targets(self._frame)
        if MOLECULE_ID not in targets:
            return None
        value = targets[MOLECULE_ID]
        return str(value)

    @property
    def conformer_id(self) -> str | None:
        """Optional conformer identity, or ``None`` if absent."""
        targets = Targets(self._frame)
        if CONFORMER_ID not in targets:
            return None
        value = targets[CONFORMER_ID]
        return str(value)

    def require_identity(self) -> str:
        """Return :attr:`molecule_id`, raising if the frame has none.

        Returns:
            The molecule identity string.

        Raises:
            KeyError: If ``molecule_id`` was not written via
                :class:`~molhub.dataset.Targets`.
        """
        mid = self.molecule_id
        if mid is None:
            raise KeyError(
                f"Frame is missing graph meta {MOLECULE_ID!r}; "
                "write it with Targets(frame).write({...})."
            )
        return mid

    def has_connectivity(self) -> bool:
        """True when a ``bonds`` block with ``atomi`` / ``atomj`` is present."""
        if "bonds" not in self._frame:
            return False
        bonds = self._frame["bonds"]
        return BOND_ATOMI in bonds and BOND_ATOMJ in bonds


@dataclass(frozen=True)
class MoleculeSplit:
    """Molecule-level train / val / test partition of a multi-conformer source.

    Partitions are **index lists into a parent** :class:`~molhub.dataset.MapDataset`.
    All conformers of one ``molecule_id`` must land in a single split.

    Attributes:
        scheme: Named scheme (see :data:`KNOWN_SPLIT_SCHEMES`).
        version: Scheme version string (e.g. ``"1"``).
        train: Parent indices for the training partition.
        val: Parent indices for validation.
        test: Parent indices for test.
    """

    scheme: str
    version: str
    train: tuple[int, ...] = field(default_factory=tuple)
    val: tuple[int, ...] = field(default_factory=tuple)
    test: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "train", tuple(self.train))
        object.__setattr__(self, "val", tuple(self.val))
        object.__setattr__(self, "test", tuple(self.test))

    # -- constructors -------------------------------------------------------

    @classmethod
    def random_molecule(
        cls,
        molecule_ids: Sequence[str],
        *,
        ratios: tuple[float, float, float] = (0.8, 0.1, 0.1),
        seed: int = 0,
        scheme: str = "molhub-random-molecule",
        version: str = "1",
    ) -> MoleculeSplit:
        """Build a molecule-level random split from per-sample molecule ids.

        Args:
            molecule_ids: Sequence of length N giving the molecule id of each
                parent sample (conformers share an id).
            ratios: ``(train, val, test)`` fractions; must sum to 1.0 within
                floating-point tolerance.
            seed: RNG seed for reproducible shuffles.
            scheme: Scheme name stored on the split.
            version: Scheme version string.

        Returns:
            A :class:`MoleculeSplit` whose index lists cover every parent index
            exactly once, with all samples of one molecule in one partition.

        Raises:
            ValueError: If *ratios* are invalid or *molecule_ids* is empty.
        """
        if not molecule_ids:
            raise ValueError("molecule_ids must be non-empty")
        train_r, val_r, test_r = ratios
        if min(train_r, val_r, test_r) < 0:
            raise ValueError(f"ratios must be non-negative, got {ratios}")
        if abs(train_r + val_r + test_r - 1.0) > 1e-9:
            raise ValueError(f"ratios must sum to 1.0, got {ratios}")

        # Group parent indices by molecule_id (preserve first-seen order).
        by_mol: dict[str, list[int]] = {}
        order: list[str] = []
        for idx, mid in enumerate(molecule_ids):
            if mid not in by_mol:
                by_mol[mid] = []
                order.append(mid)
            by_mol[mid].append(idx)

        unique = list(order)
        rng = random.Random(seed)
        rng.shuffle(unique)

        n = len(unique)
        n_train = int(n * train_r)
        n_val = int(n * val_r)
        # Remainder → test so counts always sum to n.
        n_test = n - n_train - n_val
        # Prefer exact published ratios when n is small and ratios hit exact ints.
        # For 10 mols × (0.8,0.1,0.1) → 8/1/1.
        if n_train + n_val + n_test != n:
            n_test = n - n_train - n_val

        train_mols = unique[:n_train]
        val_mols = unique[n_train : n_train + n_val]
        test_mols = unique[n_train + n_val :]

        def _indices(mols: Iterable[str]) -> tuple[int, ...]:
            out: list[int] = []
            for m in mols:
                out.extend(by_mol[m])
            return tuple(out)

        return cls(
            scheme=scheme,
            version=version,
            train=_indices(train_mols),
            val=_indices(val_mols),
            test=_indices(test_mols),
        )

    @classmethod
    def from_index_lists(
        cls,
        train: Sequence[int],
        val: Sequence[int],
        test: Sequence[int],
        *,
        scheme: str,
        version: str = "1",
    ) -> MoleculeSplit:
        """Construct from explicit, already-disjoint parent index lists.

        Raises:
            ValueError: If the three lists share any index.
        """
        t, v, te = tuple(train), tuple(val), tuple(test)
        _assert_disjoint_indices(t, v, te)
        return cls(scheme=scheme, version=version, train=t, val=v, test=te)

    @classmethod
    def from_index_files(
        cls,
        train_path: str | Path,
        val_path: str | Path,
        test_path: str | Path,
        *,
        scheme: str,
        version: str = "1",
    ) -> MoleculeSplit:
        """Load index lists from text files (one integer per line).

        Blank lines and ``#`` comments are ignored.
        """
        return cls.from_index_lists(
            _read_index_file(train_path),
            _read_index_file(val_path),
            _read_index_file(test_path),
            scheme=scheme,
            version=version,
        )

    # -- apply / validate ---------------------------------------------------

    def apply(self, source: MapDataset) -> tuple[SubsetDataset, SubsetDataset, SubsetDataset]:
        """Return named train / val / test :class:`SubsetDataset` views.

        Named ``source_id`` form::

            f"{source.source_id}#split={scheme}:train|val|test"
        """
        prefix = f"{self.scheme}"
        train = SubsetDataset(source, list(self.train), name=f"{prefix}:train")
        val = SubsetDataset(source, list(self.val), name=f"{prefix}:val")
        test = SubsetDataset(source, list(self.test), name=f"{prefix}:test")
        return train, val, test

    def assert_molecule_disjoint(self, source: MapDataset) -> None:
        """Raise if any ``molecule_id`` appears in more than one split.

        Args:
            source: Parent map dataset whose samples carry ``molecule_id``.

        Raises:
            ValueError: On cross-split molecule leakage or missing identity.
        """
        partitions = {
            "train": self.train,
            "val": self.val,
            "test": self.test,
        }
        mol_to_split: dict[str, str] = {}
        for split_name, indices in partitions.items():
            for idx in indices:
                frame = source[idx]
                mid = MolecularFrame(frame).require_identity()
                prior = mol_to_split.get(mid)
                if prior is not None and prior != split_name:
                    raise ValueError(
                        f"molecule_id {mid!r} appears in both {prior!r} and "
                        f"{split_name!r}; splits must be molecule-level disjoint."
                    )
                mol_to_split[mid] = split_name


def _assert_disjoint_indices(
    train: Sequence[int],
    val: Sequence[int],
    test: Sequence[int],
) -> None:
    sets = {
        "train": set(train),
        "val": set(val),
        "test": set(test),
    }
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = sets[a] & sets[b]
        if overlap:
            raise ValueError(
                f"index lists for {a!r} and {b!r} overlap at indices "
                f"{sorted(overlap)[:8]}{'…' if len(overlap) > 8 else ''}"
            )


def _read_index_file(path: str | Path) -> list[int]:
    indices: list[int] = []
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        indices.append(int(line.split()[0]))
    return indices
