"""ZINC GAFF 1.81 atom-typing recovery dataset (Validation A packaging).

Coordinate: ``dataset:espaloma/zinc-typing@1``.

Each sample is one molecule (topological typing task): covalent graph plus
legacy GAFF 1.81 atom-type string labels. Coordinates are optional (Å when
present). Energies and forces are not part of this dataset.

The published Espaloma typing accuracy (~99.1%) is a **reference**, not a
packaging hard gate — this module only delivers graphs and labels.

Molecule-level **80 : 10 : 10** train / val / test splits follow the
Espaloma-original recipe; all atoms of a molecule stay in one split.

References:
    Wang et al., GAFF 1.81, *J. Comput. Chem.* 2004.
    Wang, Fass, Greene, et al., *Chem. Sci.* 2022.
    DOI: 10.1039/D2SC02739A; arXiv:2010.01196.

Usage::

    from molhub.dataset import ZincTypingDataset

    ds = ZincTypingDataset(root, split="train", download=False)
    frame = ds[0]  # molpy.Frame with atoms.atom_type + bonds
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from molpy import Block, Element, Frame

from molhub.dataset.hub import ArtifactHub
from molhub.dataset.meta import Targets
from molhub.dataset.molecular import MOLECULE_ID
from molhub.dataset.protocol import TargetSchema
from molhub.molhub import Molhub

COORDINATE = "dataset:espaloma/zinc-typing@1"
"""Sole registry handle. Upstream locators live only in the manifest."""

_SPLITS: frozenset[str] = frozenset({"train", "val", "test"})

_ELEMENT_SYMBOLS: dict[int, str] = {
    1: "H",
    6: "C",
    7: "N",
    8: "O",
    9: "F",
    15: "P",
    16: "S",
    17: "Cl",
    35: "Br",
    53: "I",
}


def _is_present(path: Path) -> bool:
    """True when *path* exists and is a non-empty file or non-empty directory."""
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(path.iterdir())
    return False


def _symbol_for(z: int) -> str:
    z_int = int(z)
    if z_int in _ELEMENT_SYMBOLS:
        return _ELEMENT_SYMBOLS[z_int]
    try:
        return str(Element(z_int).symbol)
    except Exception:
        return "?"


def _load_molecule(mol_dir: Path, molecule_id: str) -> Frame:
    """Load one molecule directory into a :class:`~molpy.Frame`."""
    atoms_path = mol_dir / "atoms.npz"
    bonds_path = mol_dir / "bonds.npz"
    if not atoms_path.is_file():
        raise FileNotFoundError(f"zinc-typing molecule missing atoms.npz: {mol_dir}")
    if not bonds_path.is_file():
        raise FileNotFoundError(f"zinc-typing molecule missing bonds.npz: {mol_dir}")

    atoms_data = np.load(atoms_path, allow_pickle=False)
    if "number" not in atoms_data or "atom_type" not in atoms_data:
        raise KeyError(f"{atoms_path} must contain 'number' and 'atom_type'")
    numbers = np.asarray(atoms_data["number"], dtype=np.int64)
    atom_types = np.asarray(atoms_data["atom_type"])
    # Normalise string dtypes to unicode for molpy Block columns.
    if atom_types.dtype.kind in ("S", "U", "O"):
        atom_types = np.array([str(x) for x in atom_types], dtype="U16")
    else:
        atom_types = atom_types.astype("U16")

    if "element" in atoms_data:
        elements = np.asarray(atoms_data["element"])
        elements = np.array([str(x) for x in elements], dtype="U3")
    else:
        elements = np.array([_symbol_for(int(z)) for z in numbers], dtype="U3")

    if len(numbers) != len(atom_types) or len(numbers) != len(elements):
        raise ValueError(
            f"{molecule_id}: atom columns length mismatch "
            f"number={len(numbers)} element={len(elements)} atom_type={len(atom_types)}"
        )

    atoms_blk = Block()
    atoms_blk["element"] = elements
    atoms_blk["number"] = numbers
    atoms_blk["atom_type"] = atom_types
    if all(k in atoms_data for k in ("x", "y", "z")):
        atoms_blk["x"] = np.asarray(atoms_data["x"], dtype=np.float64)
        atoms_blk["y"] = np.asarray(atoms_data["y"], dtype=np.float64)
        atoms_blk["z"] = np.asarray(atoms_data["z"], dtype=np.float64)

    bonds_data = np.load(bonds_path, allow_pickle=False)
    if "atomi" not in bonds_data or "atomj" not in bonds_data:
        raise KeyError(f"{bonds_path} must contain 'atomi' and 'atomj'")
    bonds_blk = Block()
    bonds_blk["atomi"] = np.asarray(bonds_data["atomi"], dtype=np.int64)
    bonds_blk["atomj"] = np.asarray(bonds_data["atomj"], dtype=np.int64)

    frame = Frame()
    frame["atoms"] = atoms_blk
    frame["bonds"] = bonds_blk
    Targets(frame).write({MOLECULE_ID: str(molecule_id)})
    return frame


def _read_splits(root: Path) -> dict[str, list[str]]:
    path = root / "splits.json"
    if not path.is_file():
        raise FileNotFoundError(f"zinc-typing payload missing splits.json under {root}")
    raw = json.loads(path.read_text())
    out: dict[str, list[str]] = {}
    for key in ("train", "val", "test"):
        if key not in raw:
            raise KeyError(f"splits.json missing {key!r}")
        out[key] = [str(x) for x in raw[key]]
    return out


class ZincTypingDataset:
    """Map-style dataset for Espaloma ZINC GAFF 1.81 typing recovery.

    Samples are molpy :class:`~molpy.Frame` objects with:

    * graph meta ``molecule_id``
    * ``atoms.element``, ``atoms.number``, ``atoms.atom_type`` (GAFF 1.81)
    * optional ``atoms.x/y/z`` in Å
    * ``bonds.atomi`` / ``bonds.atomj`` covalent topology

    Payload layout (role ``main``, after fetch / offline root)::

        <root>/
          splits.json
          mols/<molecule_id>/atoms.npz
          mols/<molecule_id>/bonds.npz

    Args:
        root: Offline payload directory (used when *download* is False, and as
            the local cache path name when True only if already populated).
        split: One of ``"train"``, ``"val"``, ``"test"``.
        download: Fetch role ``main`` through *hub* when the offline tree is
            absent.
        hub: :class:`~molhub.dataset.hub.ArtifactHub` implementation.

    Class attributes:
        TARGET_SCHEMA: Atom-level ``atom_type`` only (chemical perception).
        COORDINATE: Registry coordinate string.
        SPLITS: Allowed split names.
    """

    COORDINATE: str = COORDINATE
    SPLITS: frozenset[str] = _SPLITS
    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset(),
        atom_level=frozenset({"atom_type"}),
        chemical_perception=frozenset({"atom_type"}),
    )

    def __init__(
        self,
        root: str | Path,
        *,
        split: str = "train",
        download: bool = True,
        hub: ArtifactHub | None = None,
    ) -> None:
        if split not in _SPLITS:
            raise ValueError(f"Unknown zinc-typing split {split!r}. Available: {sorted(_SPLITS)}")
        self.split = split
        self.root = Path(root)
        self._data_root = self._locate(download, hub)
        self._split_table = _read_splits(self._data_root)
        self._molecule_ids = list(self._split_table[split])
        mols_dir = self._data_root / "mols"
        self._frames: list[Frame] = [
            _load_molecule(mols_dir / mid, mid) for mid in self._molecule_ids
        ]

    def _locate(self, download: bool, hub: ArtifactHub | None) -> Path:
        """Return the payload root directory.

        Offline mode requires *root* itself to hold ``splits.json``. Download
        mode asks the hub for role ``main`` at :data:`COORDINATE` and expects
        the returned path to be that directory (or a directory containing it).
        """
        offline = self.root
        if _is_present(offline / "splits.json"):
            return offline
        if not download:
            raise FileNotFoundError(
                f"zinc-typing payload not found under {offline} "
                f"(expected splits.json). Pass download=True to fetch "
                f"{COORDINATE}."
            )
        paths = (hub or Molhub()).fetch(COORDINATE, roles=["main"])
        main = paths["main"]
        if main.is_dir() and _is_present(main / "splits.json"):
            return main
        if main.is_dir() and _is_present(main / "zinc-typing" / "splits.json"):
            return main / "zinc-typing"
        # Hub may return a file path that is itself the tree root name.
        if main.is_file() and main.name == "splits.json":
            return main.parent
        raise FileNotFoundError(f"hub returned main={main} without a zinc-typing splits.json tree")

    @property
    def source_id(self) -> str:
        """Coordinate with split qualifier."""
        return f"{COORDINATE}#split={self.split}"

    @property
    def molecule_ids(self) -> list[str]:
        """Molecule ids in this split, source order."""
        return list(self._molecule_ids)

    @property
    def split_table(self) -> dict[str, list[str]]:
        """Full train/val/test molecule-id table from the payload."""
        return {k: list(v) for k, v in self._split_table.items()}

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, idx: int) -> Frame:
        return self._frames[idx]
