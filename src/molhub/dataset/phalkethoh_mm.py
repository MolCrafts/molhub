"""PhAlkEthOH MM-small multi-conformer dataset (Espaloma MM toy fit).

Coordinate: ``dataset:espaloma/phalkethoh-mm-small@1``.

One :class:`~molpy.Frame` per conformer. Conformations of the same molecule
share ``molecule_id``; ``conf_index`` distinguishes conformers. Boundary units
match the published Espaloma toy experiment exactly:

* coordinates — Å
* ``mm_energy`` — kcal/mol
* forces (optional) — kcal/(mol·Å)

No unit conversion is applied. Molecule-level 80:10:10 splits keep all
conformers of one molecule in a single partition.

References:
    Wang, Fass, Greene, et al. "End-to-end differentiable molecular mechanics
    force field construction." arXiv:2010.01196; *Chem. Sci.* 2022.
    DOI: 10.1039/D2SC02739A.

Usage::

    from molhub.dataset import PhalkethohMMDataset

    ds = PhalkethohMMDataset(root, split="train", download=False)
    frame = ds[0]
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
from molpy import Block, Element, Frame

from molhub.dataset.hub import ArtifactHub
from molhub.dataset.meta import Targets
from molhub.dataset.molecular import CONFORMER_ID, MOLECULE_ID
from molhub.dataset.protocol import TargetSchema
from molhub.molhub import Molhub

COORDINATE = "dataset:espaloma/phalkethoh-mm-small@1"
"""Sole registry handle. Locators live only in the manifest."""

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
}


def _symbol_for(z: int) -> str:
    z_int = int(z)
    if z_int in _ELEMENT_SYMBOLS:
        return _ELEMENT_SYMBOLS[z_int]
    try:
        return str(Element(z_int).symbol)
    except Exception:
        return "?"


def _is_tree(root: Path) -> bool:
    return (root / "splits.json").is_file() and (root / "mols").is_dir()


def _extract_zip_if_needed(main: Path, cache_dir: Path) -> Path:
    """Return a directory tree for *main* (zip or already-extracted dir)."""
    if main.is_dir() and _is_tree(main):
        return main
    if main.is_dir() and _is_tree(main / "phalkethoh-mm-small"):
        return main / "phalkethoh-mm-small"
    if main.is_file() and zipfile.is_zipfile(main):
        dest = cache_dir / "phalkethoh-mm-small-extracted"
        if not _is_tree(dest):
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(main) as zf:
                zf.extractall(dest)
        # Zip may contain a single top-level folder.
        if _is_tree(dest):
            return dest
        children = [p for p in dest.iterdir() if p.is_dir()]
        for child in children:
            if _is_tree(child):
                return child
        raise FileNotFoundError(f"extracted zip {main} has no splits.json tree")
    raise FileNotFoundError(f"phalkethoh main artifact not a payload tree or zip: {main}")


def _read_splits(root: Path) -> dict[str, list[str]]:
    raw = json.loads((root / "splits.json").read_text())
    out: dict[str, list[str]] = {}
    for key in ("train", "val", "test"):
        if key not in raw:
            raise KeyError(f"splits.json missing {key!r}")
        out[key] = [str(x) for x in raw[key]]
    return out


def _load_molecule_confs(mol_dir: Path, molecule_id: str) -> list[Frame]:
    atoms_path = mol_dir / "atoms.npz"
    confs_path = mol_dir / "confs.npz"
    if not atoms_path.is_file() or not confs_path.is_file():
        raise FileNotFoundError(f"phalkethoh molecule incomplete: {mol_dir}")

    atoms = np.load(atoms_path, allow_pickle=False)
    if "number" not in atoms:
        raise KeyError(f"{atoms_path} missing 'number'")
    numbers = np.asarray(atoms["number"], dtype=np.int64)
    n_atoms = len(numbers)
    if "element" in atoms:
        elements = np.array([str(x) for x in atoms["element"]], dtype="U3")
    else:
        elements = np.array([_symbol_for(int(z)) for z in numbers], dtype="U3")

    bonds_blk: Block | None = None
    if "atomi" in atoms and "atomj" in atoms:
        bonds_blk = Block()
        bonds_blk["atomi"] = np.asarray(atoms["atomi"], dtype=np.int64)
        bonds_blk["atomj"] = np.asarray(atoms["atomj"], dtype=np.int64)
    else:
        # Optional dedicated bonds.npz
        bonds_path = mol_dir / "bonds.npz"
        if bonds_path.is_file():
            b = np.load(bonds_path, allow_pickle=False)
            bonds_blk = Block()
            bonds_blk["atomi"] = np.asarray(b["atomi"], dtype=np.int64)
            bonds_blk["atomj"] = np.asarray(b["atomj"], dtype=np.int64)

    confs = np.load(confs_path, allow_pickle=False)
    if "coords" not in confs or "mm_energy" not in confs:
        raise KeyError(f"{confs_path} must contain 'coords' and 'mm_energy'")
    coords = np.asarray(confs["coords"], dtype=np.float64)
    energies = np.asarray(confs["mm_energy"], dtype=np.float64).reshape(-1)
    if coords.ndim != 3 or coords.shape[1:] != (n_atoms, 3):
        raise ValueError(
            f"{molecule_id}: coords shape {coords.shape} incompatible with n_atoms={n_atoms}"
        )
    if coords.shape[0] != len(energies):
        raise ValueError(f"{molecule_id}: coords/energy length mismatch")
    forces = confs["forces"] if "forces" in confs else None
    if forces is not None:
        forces = np.asarray(forces, dtype=np.float64)
        if forces.shape != coords.shape:
            raise ValueError(f"{molecule_id}: forces shape {forces.shape} != coords")

    legacy_path = mol_dir / "legacy_params.json"
    legacy: str | None = None
    if legacy_path.is_file():
        # Store as JSON string meta so MetaCodec (str only) can hold it.
        legacy = legacy_path.read_text()

    frames: list[Frame] = []
    for conf_i in range(coords.shape[0]):
        atoms_blk = Block()
        atoms_blk["element"] = elements
        atoms_blk["number"] = numbers
        atoms_blk["x"] = coords[conf_i, :, 0].copy()
        atoms_blk["y"] = coords[conf_i, :, 1].copy()
        atoms_blk["z"] = coords[conf_i, :, 2].copy()
        if forces is not None:
            atoms_blk["fx"] = forces[conf_i, :, 0].copy()
            atoms_blk["fy"] = forces[conf_i, :, 1].copy()
            atoms_blk["fz"] = forces[conf_i, :, 2].copy()

        frame = Frame()
        frame["atoms"] = atoms_blk
        if bonds_blk is not None:
            frame["bonds"] = bonds_blk

        meta: dict[str, object] = {
            MOLECULE_ID: str(molecule_id),
            CONFORMER_ID: str(conf_i),
            "conf_index": int(conf_i),
            "mm_energy": float(energies[conf_i]),
        }
        if legacy is not None:
            meta["legacy_params_json"] = legacy
        Targets(frame).write(meta)
        frames.append(frame)
    return frames


class PhalkethohMMDataset:
    """Map-style PhAlkEthOH MM-small multi-conformer dataset.

    Args:
        root: Offline payload directory or extract cache parent.
        download: Fetch role ``main`` when the offline tree is missing.
        hub: :class:`~molhub.dataset.hub.ArtifactHub` implementation.
        split: ``None`` for the full conformer list, or ``train``/``val``/``test``.

    Class attributes:
        TARGET_SCHEMA: graph ``mm_energy``, atom ``forces``.
        COORDINATE: Registry coordinate.
    """

    COORDINATE: str = COORDINATE
    SPLITS: frozenset[str] = _SPLITS
    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset({"mm_energy"}),
        atom_level=frozenset({"forces"}),
        mm=frozenset({"mm_energy", "forces"}),
    )

    def __init__(
        self,
        root: str | Path,
        *,
        download: bool = True,
        hub: ArtifactHub | None = None,
        split: str | None = None,
    ) -> None:
        if split is not None and split not in _SPLITS:
            raise ValueError(f"Unknown phalkethoh split {split!r}. Available: {sorted(_SPLITS)}")
        self.split = split
        self.root = Path(root)
        self._data_root = self._locate(download, hub)
        self._split_table = _read_splits(self._data_root)
        if split is None:
            # Preserve molecule order: train then val then test as published.
            mol_ids: list[str] = []
            seen: set[str] = set()
            for key in ("train", "val", "test"):
                for mid in self._split_table[key]:
                    if mid not in seen:
                        mol_ids.append(mid)
                        seen.add(mid)
            # Also include any mols/ entries not listed (defensive).
            mols_dir = self._data_root / "mols"
            for child in sorted(mols_dir.iterdir()) if mols_dir.is_dir() else []:
                if child.is_dir() and child.name not in seen:
                    mol_ids.append(child.name)
                    seen.add(child.name)
        else:
            mol_ids = list(self._split_table[split])

        self._molecule_ids = list(mol_ids)
        self._frames: list[Frame] = []
        mols_dir = self._data_root / "mols"
        for mid in mol_ids:
            self._frames.extend(_load_molecule_confs(mols_dir / mid, mid))

    def _locate(self, download: bool, hub: ArtifactHub | None) -> Path:
        if _is_tree(self.root):
            return self.root
        if not download:
            raise FileNotFoundError(
                f"phalkethoh payload not found under {self.root} "
                f"(expected splits.json + mols/). Pass download=True to fetch "
                f"{COORDINATE}."
            )
        paths = (hub or Molhub()).fetch(COORDINATE, roles=["main"])
        main = paths["main"]
        cache_dir = self.root if self.root.exists() else main.parent
        cache_dir.mkdir(parents=True, exist_ok=True)
        return _extract_zip_if_needed(main, cache_dir)

    @property
    def source_id(self) -> str:
        if self.split is None:
            return COORDINATE
        return f"{COORDINATE}#split={self.split}"

    @property
    def molecule_ids(self) -> list[str]:
        """Distinct molecule ids in this view (split or full)."""
        return list(self._molecule_ids)

    @property
    def split_table(self) -> dict[str, list[str]]:
        return {k: list(v) for k, v in self._split_table.items()}

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, idx: int) -> Frame:
        return self._frames[idx]
