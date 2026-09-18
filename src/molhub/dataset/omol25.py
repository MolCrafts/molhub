"""OMol25 energy+force records as molpy frames.

The published splits are public ``*.aselmdb`` tarballs on Meta's CDN
(``dataset:fairchem/omol25@1``). HuggingFace ``facebook/OMol25`` is only the
gated card and checkpoints — login/agree there if you need the card;
:class:`~molhub.Molhub.fetch` pulls the tarball over plain HTTPS.

:class:`OMol25Lmdb` reads those files with :class:`~molhub.io.lmdb.Lmdb`
and yields molpy frames; :meth:`OMol25Lmdb.record` and
:meth:`OMol25Lmdb.cache` are the raw-row surface for callers that
index or subsample without building frames.
:class:`OMol25` defaults to the official 4M train. Official val is a
pinned tarball; domain views are in-memory :meth:`OMol25.assignment`
projections of that val, wrapped by the caller in
:class:`~molhub.dataset.protocol.SubsetDataset`. ``omol-elem-refs`` is a
Manifest file role fetched with :meth:`~molhub.dataset.hub.ArtifactHub.fetch`
— hosted, not fitted, and not an :class:`OMol25` role.
:class:`OMol25Dataset` is the packed-NPZ form used by tests.
:class:`OMol25Small` filters either source down to Neutral singlet organics
with inferred bonds. Missing energy or forces refuse.

Every frame keeps the published native units — energy eV, forces eV/Å,
positions Å — exactly as recorded upstream. molhub never converts units;
consumers convert (e.g. :class:`~molhub.dataset.transforms.UnitConvert`).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from tarfile import TarFile
from typing import Any, Protocol

import numpy as np
from molpy import Block, Frame

from molhub.cache import CountSidecar
from molhub.coordinate import Coordinate
from molhub.dataset.bonds import (
    _checked_numbers,
    _element_tables,
    infer_bonds,
)
from molhub.dataset.definition import dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import Dataset, TargetSchema
from molhub.dataset.statistic import StatisticMixin, frame_field
from molhub.io.lmdb import Lmdb
from molhub.manifest import Artifact, Manifest, TargetDeclaration
from molhub.molhub import Molhub
from molhub.sources import Locator

__all__ = [
    "COORDINATE",
    "SMALL_COORDINATE",
    "MANIFEST",
    "OMol25",
    "OMol25Dataset",
    "OMol25Lmdb",
    "OMol25Small",
    "OMol25SmallFilter",
    "infer_bonds",
]

COORDINATE = "dataset:fairchem/omol25@1"
SMALL_COORDINATE = "dataset:molcrafts/omol25-small@1"

MANIFEST = Manifest(
    coordinate=Coordinate.parse(COORDINATE),
    title="OMol25 — Open Molecules 2025 energy and forces",
    description=(
        "ωB97M-V/def2-TZVPD single points with total energy (eV) and forces (eV/Å); "
        "positions Å. Files are *.aselmdb tarballs. 4m is the published 4-million "
        "training subsample; val is official general validation; val-neutral is the "
        "small Neutral smoke tarball, never protocol val. Domain views are "
        "assignment() projections of official val. omol-elem-refs hosts the combined "
        "element table YAML as a Manifest file role; it is not fitted here. Not the "
        "100M All dump."
    ),
    license="CC-BY-4.0",
    doi="10.48550/arXiv.2505.08762",
    artifacts={
        "val-neutral": Artifact(
            role="val-neutral",
            filename="val_neutral.tar.gz",
            format="aselmdb-tar",
            locators=(
                Locator.parse(
                    "https://dl.fbaipublicfiles.com/opencatalystproject/data/omol/250514/neutral_val.tar.gz"
                ),
            ),
            size=124_585_282,
        ),
        "4m": Artifact(
            role="4m",
            filename="train_4M.tar.gz",
            format="aselmdb-tar",
            locators=(
                Locator.parse(
                    "https://dl.fbaipublicfiles.com/opencatalystproject/data/omol/250514/train_4M.tar.gz"
                ),
            ),
            size=19_983_081_456,
        ),
        "val": Artifact(
            role="val",
            filename="val.tar.gz",
            format="aselmdb-tar",
            locators=(
                Locator.parse(
                    "https://dl.fbaipublicfiles.com/opencatalystproject/data/omol/250514/val.tar.gz"
                ),
            ),
            size=21_293_980_744,
        ),
        "omol-elem-refs": Artifact(
            role="omol-elem-refs",
            filename="uma_v1_hof_lin_refs.yaml",
            format="yaml",
            locators=(
                Locator.parse(
                    "https://raw.githubusercontent.com/facebookresearch/fairchem/"
                    "41d36dc6bf8ced6348dc73e6aaf54d0527ebd8c9/configs/allscaip/"
                    "element_refs/uma_v1_hof_lin_refs.yaml"
                ),
            ),
            size=11_549,
        ),
    },
    targets=TargetDeclaration(graph_level=("energy",), atom_level=("forces",)),
)

_TARBALL_ROLES: tuple[str, ...] = ("4m", "val", "val-neutral")
_ASSIGNMENT_DATA_IDS: dict[str, frozenset[str]] = {
    "val_metal_complexes": frozenset({"metal_complexes"}),
    "val_electrolytes": frozenset({"elytes"}),
    "val_biomolecules": frozenset({"biomolecules"}),
    "val_spice": frozenset({"spice"}),
    "val_neutralorganics": frozenset({"ani2x", "orbnet_denali", "geom_orca6", "trans1x", "rgd"}),
}

_REQUIRED = ("n_atoms", "Z", "pos", "energy", "forces", "charge", "spin")
_ALLOWED_Z = np.array([1, 6, 7, 8, 9, 15, 16, 17, 35, 53], dtype=np.int64)
_EXCLUDE_DOMAINS = frozenset(
    {
        "biomolecule",
        "biomolecules",
        "metal",
        "metals",
        "metal_complex",
        "metal-complex",
        "electrolyte",
        "electrolytes",
        "reactivity",
        "rmechdb",
        "pmechdb",
        "ani-1xbb",
    }
)


class _MapStyle(Protocol):
    def __len__(self) -> int: ...

    def __getitem__(self, idx: int) -> Sequence[Frame]: ...

    @property
    def source_id(self) -> str: ...


def _frame_from_record(record: dict[str, Any]) -> Frame:
    energy = record.get("energy")
    forces = record.get("forces")
    if energy is None:
        raise KeyError("OMol25 record has no energy")
    if forces is None:
        raise KeyError("OMol25 record has no forces")
    numbers = _checked_numbers(record["numbers"])
    pos = np.asarray(record["positions"], dtype=np.float64)
    force = np.asarray(forces, dtype=np.float64)
    if pos.shape != (numbers.shape[0], 3) or force.shape != pos.shape:
        raise ValueError(
            f"OMol25 geometry/force shape mismatch: Z={numbers.shape} "
            f"pos={pos.shape} forces={force.shape}"
        )
    extra = dict(record.get("data") or {})
    symbols = _element_tables()[0][numbers]
    frame = Frame()
    frame["atoms"] = Block(
        {
            "element": symbols,
            "number": numbers,
            "x": pos[:, 0],
            "y": pos[:, 1],
            "z": pos[:, 2],
            "fx": force[:, 0],
            "fy": force[:, 1],
            "fz": force[:, 2],
        }
    )
    charge = extra.get("charge", record.get("charge", 0) or 0)
    frame.meta = {
        "energy": float(energy),
        "charge": int(charge),
        "spin": int(extra.get("spin", 1)),
        "domain": str(extra.get("data_id", "")),
    }
    return frame


def _atom_ptr(n_atoms: np.ndarray) -> np.ndarray:
    ptr = np.zeros(int(n_atoms.shape[0]) + 1, dtype=np.int64)
    np.cumsum(n_atoms, out=ptr[1:])
    return ptr


_frame_field = frame_field


def _payload_dtype_name(value: object) -> str:
    dtype = np.asarray(value).dtype
    if np.issubdtype(dtype, np.floating):
        return "float64"
    return "int32"


def _count_table_atoms(path: str) -> dict[int, int]:
    """Per-row atom counts of one ``*.aselmdb`` file — raw decode, no frames.

    Module-level so :meth:`OMol25Lmdb.cache` can fan it out over a
    process pool; each worker opens its own read-only environment.
    """
    table = Lmdb(path)
    try:
        return {
            int(row): int(np.asarray(table.get(row)["numbers"]).reshape(-1).shape[0])
            for row in table.ids
        }
    finally:
        table.close()


def _unwrap(value: Any) -> Any:
    """A molpy ``MetaValue``'s payload, or *value* when it is already plain.

    The default of the ``getattr`` **is the value itself**. Passing a constant
    instead silently substitutes that constant for every unwrapped scalar,
    which is how an open-shell frame with ``spin=3`` read back as ``spin=1``.
    """
    return getattr(value, "value", value)


class OMol25SmallFilter:
    """Keep / drop one OMol25 frame for the v0 small-molecule train.

    Args:
        max_atoms: Inclusive atom-count cap (plan v0: 32).
    """

    def __init__(self, *, max_atoms: int = 32) -> None:
        self.max_atoms = int(max_atoms)

    def reason(self, frame: Frame) -> str | None:
        """Return the drop reason, or ``None`` if the frame is kept."""
        atoms = frame["atoms"]
        numbers = np.asarray(atoms["number"], dtype=np.int64).reshape(-1)
        n_atoms = int(numbers.shape[0])
        if n_atoms == 0 or n_atoms > self.max_atoms:
            return "n_atoms"
        if not np.isin(numbers, _ALLOWED_Z).all():
            return "element"
        meta = frame.meta
        # molpy 0.14 ``Frame.meta`` values are ``MetaValue`` wrappers; int()
        # of the wrapper raises. Unwrap like ``_frame_field`` / ``_bonded``:
        # the getattr default must be **the value itself**, so an unwrapped
        # int or str survives. With a constant default instead, a plain
        # ``spin=3`` reads back as 1 and an open-shell frame is silently kept.
        charge = _unwrap(meta.get("charge", 0))
        if int(charge) != 0:
            return "charge"
        spin = _unwrap(meta.get("spin", 1))
        if int(spin) != 1:
            return "spin"
        domain = str(_unwrap(meta.get("domain", ""))).strip().lower()
        if domain and domain in _EXCLUDE_DOMAINS:
            return "domain"
        return None


class OMol25Dataset(Dataset, StatisticMixin):
    """Map-style view of a packed OMol25 NPZ (native eV / eV·Å⁻¹).

    Required arrays: ``n_atoms`` ``(C,)``, ``Z`` ``(N,)``, ``pos`` ``(N, 3)``,
    ``energy`` ``(C,)``, ``forces`` ``(N, 3)``, ``charge`` ``(C,)``,
    ``spin`` ``(C,)``. Optional ``domain`` ``(C,)``.

    Each sample is a length-1 ``Sequence[Frame]``. Energy lives in
    ``frame.meta``; forces are ``fx`` / ``fy`` / ``fz``. No bonds.

    Args:
        path: Packed NPZ written from the official 4M extract.

    Raises:
        FileNotFoundError: *path* is missing or empty.
        KeyError: A required array is absent.
        ValueError: A record is missing energy or forces, or the packed
            lengths do not add up.
    """

    COORDINATE = COORDINATE
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
        qm=frozenset({"energy", "forces"}),
    )

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file() or self.path.stat().st_size == 0:
            raise FileNotFoundError(f"OMol25 packed file is missing or empty: {self.path}")
        data = np.load(self.path, allow_pickle=False)
        for key in _REQUIRED:
            if key not in data:
                raise KeyError(f"OMol25 packed file missing required key {key!r}")
        self._n_atoms = np.asarray(data["n_atoms"], dtype=np.int64).reshape(-1)
        self._ptr = _atom_ptr(self._n_atoms)
        self._z = np.asarray(data["Z"], dtype=np.int64).reshape(-1)
        self._pos = np.asarray(data["pos"], dtype=np.float64)
        self._energy = np.asarray(data["energy"], dtype=np.float64).reshape(-1)
        self._forces = np.asarray(data["forces"], dtype=np.float64)
        self._charge = np.asarray(data["charge"], dtype=np.int64).reshape(-1)
        self._spin = np.asarray(data["spin"], dtype=np.int64).reshape(-1)
        self._domain = (
            np.asarray(data["domain"]).reshape(-1)
            if "domain" in data
            else np.array([""] * self._energy.shape[0])
        )
        n = int(self._energy.shape[0])
        if self._pos.ndim != 2 or self._pos.shape[1] != 3:
            raise ValueError(f"OMol25 pos must be (N, 3), got {self._pos.shape}")
        if self._forces.shape != self._pos.shape:
            raise ValueError(f"OMol25 forces shape {self._forces.shape} != pos {self._pos.shape}")
        if int(self._ptr[-1]) != int(self._z.shape[0]) or int(self._z.shape[0]) != int(
            self._pos.shape[0]
        ):
            raise ValueError("OMol25 packed atom counts do not match Z/pos length")
        if not (
            self._n_atoms.shape[0]
            == self._energy.shape[0]
            == self._charge.shape[0]
            == self._spin.shape[0]
            == self._domain.shape[0]
        ):
            raise ValueError("OMol25 packed per-frame arrays disagree on count")
        if n == 0:
            raise ValueError("OMol25 packed file has no records")
        if not np.isfinite(self._energy).all():
            raise ValueError("OMol25 energy contains NaN or Inf")
        if not np.isfinite(self._forces).all():
            raise ValueError("OMol25 forces contain NaN or Inf")

    @property
    def source_id(self) -> str:
        return f"{COORDINATE}#packed={self.path.name}"

    def __len__(self) -> int:
        return int(self._energy.shape[0])

    #: The packed NPZ already holds the atom count per row, so the count is a
    #: declaration rather than a method: nothing is decoded and nothing is
    #: cached, because there is nothing expensive to cache.
    counted_tables = {"atoms": "_n_atoms"}

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        if idx < 0:
            idx += len(self)
        if idx < 0 or idx >= len(self):
            raise IndexError(idx)
        start = int(self._ptr[idx])
        stop = int(self._ptr[idx + 1])
        z = _checked_numbers(self._z[start:stop])
        pos = self._pos[start:stop]
        forces = self._forces[start:stop]
        atoms = Block()
        atoms["element"] = _element_tables()[0][z]
        atoms["number"] = z
        atoms["x"] = pos[:, 0].copy()
        atoms["y"] = pos[:, 1].copy()
        atoms["z"] = pos[:, 2].copy()
        atoms["fx"] = forces[:, 0].copy()
        atoms["fy"] = forces[:, 1].copy()
        atoms["fz"] = forces[:, 2].copy()
        frame = Frame()
        frame["atoms"] = atoms
        frame.meta = {
            "energy": float(self._energy[idx]),
            "charge": int(self._charge[idx]),
            "spin": int(self._spin[idx]),
            "domain": str(self._domain[idx]),
            "source_record_id": str(idx),
            "molecule_id": str(idx),
        }
        return (frame,)


class OMol25Lmdb(Dataset, StatisticMixin):
    """One extracted OMol25 ``*.aselmdb`` directory as molpy frames.

    Each sample is a length-1 collection. Energy is ``frame.meta['energy']``
    in eV; forces are ``fx``/``fy``/``fz`` in eV/Å; positions ``x``/``y``/``z``
    are Å. No bonds.

    :meth:`record` and :meth:`cache` expose the raw-row surface so
    indexing, subsampling and reference-energy fits never pay the molpy
    Frame construction, and never reach into private state.

    Instances pickle: open LMDB environments are dropped on ``__getstate__``
    and reopened lazily per table in the receiving process, so a view can be
    handed to spawned DataLoader workers without copying payload bytes. The
    row index is a compact ``(rows, 2)`` int64 array, not per-row tuples.

    Args:
        root: Directory that contains ``dataXXXX.aselmdb`` files.
        max_rows: Stop indexing after this many rows. ``None`` reads every
            ``*.aselmdb`` file under *root*.
    """

    ADAPTER_SCHEMA_VERSION = 1
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
        qm=frozenset({"energy", "forces"}),
    )

    def __init__(self, root: str | Path, *, max_rows: int | None = None) -> None:
        self.max_rows = int(max_rows) if max_rows is not None else None
        self.root = Path(root).expanduser().resolve()
        self._parent_role: str | None = None
        self._parent_size: int | None = None
        paths: list[Path] = []
        tables: list[Lmdb | None] = []
        parts: list[np.ndarray] = []
        total = 0
        for path in sorted(self.root.glob("*.aselmdb")):
            table = Lmdb(path)
            table_idx = len(paths)
            paths.append(path)
            tables.append(table)
            ids = np.asarray(table.ids, dtype=np.int64)
            if max_rows is not None:
                ids = ids[: max(int(max_rows) - total, 0)]
            part = np.empty((ids.shape[0], 2), dtype=np.int64)
            part[:, 0] = table_idx
            part[:, 1] = ids
            parts.append(part)
            total += int(ids.shape[0])
            if max_rows is not None and total >= int(max_rows):
                break
        if total == 0:
            raise FileNotFoundError(f"No OMol25 *.aselmdb records under {self.root}")
        self._paths = tuple(paths)
        self._tables = tables
        self._index = np.concatenate(parts)

    @property
    def source_id(self) -> str:
        # max_rows changes the content of the view, so it must change the
        # cache identity too — otherwise a capped smoke view and the full
        # extract would silently share one cache entry.
        qualifier = f"#lmdb={self.root.name}"
        if self.max_rows is not None:
            qualifier += f",max_rows={self.max_rows}"
        return f"{COORDINATE}{qualifier}"

    def __len__(self) -> int:
        return int(self._index.shape[0])

    def close(self) -> None:
        """Close every open LMDB environment; rows reopen lazily on next read."""
        for table_idx, table in enumerate(self._tables):
            if table is not None:
                table.close()
                self._tables[table_idx] = None

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        # Open environments are process-local; workers reopen their own.
        state["_tables"] = [None] * len(self._paths)
        return state

    def _table(self, table_idx: int) -> Lmdb:
        table = self._tables[table_idx]
        if table is None:
            table = self._tables[table_idx] = Lmdb(self._paths[table_idx])
        return table

    def record(self, idx: int) -> dict[str, Any]:
        """Return the raw decoded LMDB record for row *idx* — no Frame.

        Keys follow the published aselmdb layout: ``numbers``, ``positions``
        (Å), ``energy`` (eV), ``forces`` (eV/Å), optional ``data`` dict with
        ``charge`` / ``spin`` / ``data_id``, plus the row ``id``.

        Args:
            idx: Row index into this view (negative indexes from the end).

        Raises:
            IndexError: *idx* is out of range.
        """
        if idx < 0:
            idx += len(self)
        if idx < 0 or idx >= len(self):
            raise IndexError(idx)
        table_idx, row_id = (int(v) for v in self._index[idx])
        return self._table(table_idx).get(row_id)

    def count_rows(self, table: str = "atoms", *, workers: int = 0) -> np.ndarray:
        """Measure the per-row length of *table*, ``(N,)`` int64.

        A verb, and an expensive one: an ASE-style LMDB has to decode a record
        to learn its length, about 15 minutes over four million rows. So the
        vector is measured once and kept in a
        :class:`~molhub.cache.CountSidecar` keyed by the shard files
        themselves — a second run, or another process, reads a ``.npy``
        instead of the database. That is why this is a method and not a
        ``counted_tables`` declaration: there is something to cache.

        Args:
            table: Frame block name. Only ``atoms`` is counted.
            workers: Processes to measure with. ``0`` or ``1`` is sequential.

        Returns:
            The per-row lengths.

        Raises:
            ValueError: *table* is not a block this container counts.
        """
        if table != "atoms":
            raise ValueError(f"OMol25 LMDB counts only the atoms table, got {table!r}")
        sidecar = CountSidecar(self._paths, "graph.natoms")
        cached = sidecar.load(n_rows=len(self))
        if cached is not None:
            return np.asarray(cached, dtype=np.int64)

        counts = np.empty(len(self), dtype=np.int64)
        if workers and int(workers) > 1:
            with ProcessPoolExecutor(max_workers=int(workers)) as pool:
                per_table = list(pool.map(_count_table_atoms, (str(p) for p in self._paths)))
            for i in range(len(self)):
                table_idx, row_id = (int(v) for v in self._index[i])
                counts[i] = per_table[table_idx][row_id]
        else:
            for i in range(len(self)):
                counts[i] = int(np.asarray(self.record(i)["numbers"]).reshape(-1).shape[0])
        sidecar.save(counts)
        return counts

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        frame = _frame_from_record(self.record(idx))
        table_idx, row_id = (int(v) for v in self._index[idx if idx >= 0 else idx + len(self)])
        record_id = f"{table_idx}:{row_id}"
        meta = {key: getattr(value, "value", value) for key, value in frame.meta.items()}
        meta["source_record_id"] = record_id
        meta.setdefault("molecule_id", record_id)
        frame.meta = meta
        return (frame,)


@dataset(
    name="omol25",
    namespace="fairchem",
    version="1",
    description=(
        "OMol25 ωB97M-V/def2-TZVPD energy (eV) and forces (eV/Å); positions Å. "
        "Tarball roles 4m, val, val-neutral; domain views are assignment() "
        "projections of official val. omol-elem-refs is a Manifest file role, "
        "not fitted. Not the 100M All dump."
    ),
    license="CC-BY-4.0",
    homepage="https://huggingface.co/facebook/OMol25",
    citation="10.48550/arXiv.2505.08762",
    tags=("omol25", "energy", "forces", "dft"),
    units={"energy": "eV", "forces": "eV/angstrom"},
)
class OMol25(Dataset, StatisticMixin):
    """One published OMol25 tarball split, fetched and read through :class:`OMol25Lmdb`.

    Construction does no IO. :meth:`load` is the download-and-extract
    boundary; after it, indexing delegates to the underlying LMDB view.
    Frames keep published DFT totals: energy eV, forces eV/Å, positions Å.
    Domain views of official val are :meth:`assignment` projections, wrapped
    by the caller in :class:`~molhub.dataset.protocol.SubsetDataset`.
    ``omol-elem-refs`` is a Manifest file role, not an :class:`OMol25` role
    and not fitted here.

    Args:
        role: Tarball role: ``4m`` (default), ``val``, or ``val-neutral``.
        max_rows: Index at most this many LMDB rows. Smoke uses a small cap
            so the full catalog is not scanned. Domain views require a
            fully indexed official val; *max_rows* is not for that.
        hub: Defaults to :class:`~molhub.molhub.Molhub`.

    Raises:
        ValueError: *role* is not a published tarball role.
    """

    COORDINATE = COORDINATE
    TARGET_SCHEMA = OMol25Lmdb.TARGET_SCHEMA

    def __init__(
        self,
        *,
        role: str = "4m",
        max_rows: int | None = None,
        hub: ArtifactHub | None = None,
    ) -> None:
        if role not in _TARBALL_ROLES:
            raise ValueError(
                f"Unknown OMol25 role {role!r}. "
                f"Tarball roles: {', '.join(_TARBALL_ROLES)}. "
                f"Assignment names: {', '.join(_ASSIGNMENT_DATA_IDS)}."
            )
        self.role = role
        self.max_rows = int(max_rows) if max_rows is not None else None
        self._hub = hub
        self._view: OMol25Lmdb | None = None

    @property
    def source_id(self) -> str:
        """Coordinate-side identity: role and row cap, never a local path."""
        qualifier = f"#role={self.role}"
        if self.max_rows is not None:
            qualifier += f",max_rows={self.max_rows}"
        return f"{COORDINATE}{qualifier}"

    def load(self) -> OMol25:
        """Fetch this role, extract the tarball once, and open the LMDB view.

        Idempotent: a second call returns immediately.

        Returns:
            This dataset, now indexable.

        Raises:
            FileNotFoundError: The fetched tarball holds no ``*.aselmdb``.
        """
        if self._view is not None:
            return self
        archive = (self._hub or Molhub()).fetch(COORDINATE, roles=[self.role])[self.role]
        dest = archive.parent / f"{self.role}-open"
        marker = dest / ".extracted"
        if not marker.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            with TarFile.open(archive, "r:*") as bundle:
                # "data" refuses path traversal and strips setuid bits.
                bundle.extractall(dest, filter="data")
            marker.write_text(self.role)
        roots = sorted({path.parent for path in dest.glob("**/*.aselmdb")})
        if not roots:
            raise FileNotFoundError(f"Fetched {self.role} but found no *.aselmdb under {dest}")
        self._view = OMol25Lmdb(roots[0], max_rows=self.max_rows)
        self._view._parent_role = self.role
        published_size = MANIFEST.artifacts[self.role].size
        self._view._parent_size = int(published_size) if published_size is not None else None
        return self

    def assignment(self) -> dict[str, list[int]]:
        """Map official-val domain names to parent indices.

        The predicate is ``record["data"]["data_id"]`` membership in the
        pinned sets (the same string stored as ``frame.meta["domain"]``).
        Multi-id views keep parent order. Indices are built in memory from
        :meth:`record`; nothing is persisted.

        Returns:
            Name → parent indices for ``val_metal_complexes``,
            ``val_electrolytes``, ``val_biomolecules``, ``val_spice``, and
            ``val_neutralorganics``.

        Raises:
            RuntimeError: :meth:`load` has not been called.
            TypeError: This role is not official val, or ``max_rows`` capped
                the index.
        """
        view = self._require_loaded()
        if self.max_rows is not None:
            raise TypeError(
                "OMol25.assignment() needs a fully indexed official val; "
                f"max_rows={self.max_rows} is set."
            )
        if self.role != "val":
            raise TypeError(
                f"OMol25 role {self.role!r} has no published assignment. "
                "Domain views are assignment() projections of official val."
            )
        views: dict[str, list[int]] = {name: [] for name in _ASSIGNMENT_DATA_IDS}
        for idx in range(len(view)):
            extra = view.record(idx).get("data") or {}
            data_id = str(extra.get("data_id", ""))
            for name, members in _ASSIGNMENT_DATA_IDS.items():
                if data_id in members:
                    views[name].append(idx)
                    break
        return views

    def _require_loaded(self) -> OMol25Lmdb:
        if self._view is None:
            raise RuntimeError("OMol25: call load() before indexing; construction does no IO.")
        return self._view

    def record(self, idx: int) -> dict[str, Any]:
        """Raw decoded LMDB record — see :meth:`OMol25Lmdb.record`."""
        return self._require_loaded().record(idx)

    def count_rows(self, table: str = "atoms", *, workers: int = 0) -> np.ndarray:
        """Measure the per-row length of *table*, through the view this wraps.

        Args:
            table: Frame block name. Only ``atoms`` is counted.
            workers: Processes to measure with when the view has to scan.

        Returns:
            The per-row lengths.
        """
        return self._require_loaded().count_rows(table, workers=workers)

    def __len__(self) -> int:
        return len(self._require_loaded())

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        return self._require_loaded()[idx]


@dataset(
    name="omol25-small",
    namespace="molcrafts",
    version="1",
    description=(
        "Selected OMol25 small-molecule slice for Class-I energy+force: "
        "4M ∩ Neutral ∩ singlet ∩ n_atoms≤32 ∩ organic Z, bonds inferred."
    ),
    license="CC-BY-4.0",
    homepage="https://huggingface.co/facebook/OMol25",
    citation="10.48550/arXiv.2505.08762",
    tags=("omol25", "energy", "forces", "small-molecule", "class-i"),
    units={"energy": "eV", "forces": "eV/angstrom"},
)
class OMol25Small(Dataset, StatisticMixin):
    """Filtered, bonded view of an :class:`OMol25Dataset` — native units.

    Frames keep the published eV / eV·Å⁻¹ labels untouched; converting is
    the consumer's job (:class:`~molhub.dataset.transforms.UnitConvert`).
    Frames that fail the small-molecule filter or have no inferred bonds
    are dropped and counted on :attr:`drop_counts`.

    Construction does no IO; :meth:`load` runs the scan. The scan is eager:
    every kept frame is held in memory, so this type fits the bounded
    small-molecule slice, not the raw 4M split — read that lazily through
    :class:`OMol25Lmdb` with caller-selected indices.

    Args:
        source: Any map-style OMol25 view (packed NPZ or official LMDB).
        max_atoms: Inclusive atom-count cap.
        limit: Stop after this many kept frames. ``None`` scans the
            whole source. Smoke and tiny-overfit use a small limit.
    """

    COORDINATE = SMALL_COORDINATE
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
        qm=frozenset({"energy", "forces"}),
    )

    def __init__(
        self,
        source: _MapStyle,
        *,
        max_atoms: int = 32,
        limit: int | None = None,
    ) -> None:
        self.source = source
        self.filter = OMol25SmallFilter(max_atoms=max_atoms)
        self.limit = int(limit) if limit is not None else None
        self.drop_counts: Counter[str] = Counter()
        self.scanned = 0
        self.kept = 0
        self._frames: tuple[Frame, ...] | None = None

    def load(self) -> OMol25Small:
        """Scan the source once, keeping filtered frames with inferred bonds.

        Idempotent: a second call returns immediately.

        Returns:
            This dataset, now indexable.
        """
        if self._frames is not None:
            return self
        kept: list[Frame] = []
        scanned = 0
        for idx in range(len(self.source)):
            if self.limit is not None and len(kept) >= self.limit:
                break
            scanned += 1
            frame = self.source[idx][0]
            reason = self.filter.reason(frame)
            if reason is not None:
                self.drop_counts[reason] += 1
                continue
            bonded = self._bonded(frame, record_id=str(idx))
            if bonded is None:
                self.drop_counts["bonds"] += 1
                continue
            kept.append(bonded)
        self._frames = tuple(kept)
        self.scanned = scanned
        self.kept = len(self._frames)
        return self

    def _require_loaded(self) -> tuple[Frame, ...]:
        if self._frames is None:
            raise RuntimeError("OMol25Small: call load() before indexing; construction does no IO.")
        return self._frames

    @staticmethod
    def _bonded(frame: Frame, *, record_id: str) -> Frame | None:
        """Attach inferred bonds and stable ids; drop bond-less frames."""
        atoms = frame["atoms"]
        numbers = _checked_numbers(atoms["number"])
        pos = np.stack(
            [np.asarray(atoms[axis], dtype=np.float64) for axis in ("x", "y", "z")],
            axis=-1,
        )
        atomi, atomj = infer_bonds(numbers, pos)
        if atomi.shape[0] == 0:
            return None
        frame["bonds"] = Block({"atomi": atomi, "atomj": atomj})
        meta = {key: getattr(value, "value", value) for key, value in frame.meta.items()}
        meta["source_record_id"] = str(meta.get("source_record_id") or record_id)
        meta["molecule_id"] = str(meta.get("molecule_id") or record_id)
        frame.meta = meta
        return frame

    @property
    def source_id(self) -> str:
        return f"{SMALL_COORDINATE}#from={self.source.source_id}"

    def __len__(self) -> int:
        return len(self._require_loaded())

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        return (self._require_loaded()[idx],)


def write_packed(path: str | Path, records: list[dict[str, Any]]) -> Path:
    """Write a packed NPZ for tests and bounded extracts. Not a public constructor."""
    if not records:
        raise ValueError("write_packed needs at least one record")
    n_atoms = np.array([int(np.asarray(item["Z"]).shape[0]) for item in records], dtype=np.int64)
    payload = {
        "n_atoms": n_atoms,
        "Z": np.concatenate([np.asarray(item["Z"], dtype=np.int64) for item in records]),
        "pos": np.concatenate([np.asarray(item["pos"], dtype=np.float64) for item in records]),
        "energy": np.array([float(item["energy"]) for item in records], dtype=np.float64),
        "forces": np.concatenate(
            [np.asarray(item["forces"], dtype=np.float64) for item in records]
        ),
        "charge": np.array([int(item.get("charge", 0)) for item in records], dtype=np.int64),
        "spin": np.array([int(item.get("spin", 1)) for item in records], dtype=np.int64),
        "domain": np.array([str(item.get("domain", "")) for item in records]),
    }
    dest = Path(path)
    # numpy's stub matches **kwds against the allow_pickle keyword; the
    # payload holds only str->ndarray entries, so the flag cannot collide.
    np.savez(dest, **payload)  # ty: ignore[invalid-argument-type]
    return dest
