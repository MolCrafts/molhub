"""Group-preserving adapters for the official THEMol HDF5 shards.

The adapters expose a shard as a map-style collection without flattening a
torsion scan or optimization trajectory into interchangeable frames.  Dataset
definition construction performs no IO; :meth:`load` is the explicit fetch and
index boundary.

**A record IS a** ``Sequence[Frame]`` (**``Sequence[Frame]``**).
One geometry is a length-1 collection — the Cartesian Hessian is a COO
``hessian`` block, the per-atom MBIS multipoles are ``atoms`` columns while
the MBIS Slater shells (one row per *shell*, not per atom) are the
``mbis_shells`` block, scalars are ``frame.meta`` entries. A multi-frame
sampling unit (a relaxation, a torsion profile) is a longer collection whose
per-frame ``meta`` carries that frame's scalars. There is no
:class:`~molpy.Trajectory` and no wrapper object on top of ``Frame``.

Laziness *between* records — one HDF5 handle per thread in
:class:`THEMolShardDataset` — is what bounds memory. Laziness
*within* one record is given up: the collection is a materialized tuple, and
the largest unit (a torsion-relax scan, ≈24 constraints × ≈10 steps × 40
atoms × 3 × 8 B ≈ 230 kB) is three orders below the block ceiling.
A record is decoded from the shard once. Later reads of that index rebuild
the frames from the byte cache and do not open the file.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable, overload

import numpy as np
from molpy import Block, Frame

from molhub.cache import CountSidecar, LmdbCache
from molhub.dataset.definition import DatasetManifest, dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.prefetch import Prefetch
from molhub.dataset.protocol import Dataset, TargetSchema
from molhub.dataset.statistic import StatisticMixin
from molhub.io.collection import instance_lock

__all__ = [
    "GAFF2_UNITS",
    "THEMOL_UNITS",
    "THEMolShardDataset",
    "THEMolHessian",
    "THEMolHessianRelax",
    "THEMolTorsionScan",
    "THEMolTorsionRelax",
    "THEMolMBIS",
]

from molhub.dataset.themol_format import (
    _ENERGY_FORCE_UNITS,
    _MBIS_ATOM_COLUMNS,
    _MBIS_SHELL_BLOCK,
    _MBIS_UNITS,
    GAFF2_UNITS,
    THEMOL_UNITS,
    TOPOLOGY_ATOM_COLUMNS,
    _read_hessian,
    _read_hessian_relax,
    _read_mbis,
    _read_torsion,
    _read_torsion_relax,
)


class THEMolShardDataset(Prefetch, Dataset, StatisticMixin):
    """Lazy map-style view of one immutable THEMol HDF5 shard.

    Each thread opens its own HDF5 handle, and a pickle drops every handle so
    a DataLoader worker reopens the file itself. Only group keys are indexed
    in memory. ``__getitem__`` and ``__getitems__`` both stage the record's
    arrays off the file and build frames on the calling thread.

    The first read of a record stores those frames in :attr:`cache`. A
    later read rebuilds them from the cache on the calling thread and does
    not open the shard. ``cache=False`` keeps every read on the shard.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        source_id: str,
        reader: Callable[[Any, str, str], Sequence[Frame]],
        manifest: DatasetManifest,
        cache: bool = True,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file() or self.path.stat().st_size == 0:
            raise FileNotFoundError(f"THEMol shard is missing or empty: {self.path}")
        self.source_id = source_id
        #: What the definition declared. Carried onto the loaded dataset so a
        #: consumer can read the published units off the object it holds
        #: instead of restating them (:class:`~molhub.dataset.protocol.DeclaredDataset`).
        self.manifest = manifest
        self._reader = reader
        self._keys = self._index_keys()
        name = getattr(reader, "__name__", "reader")
        self.cache = LmdbCache([self.path], f"themol.rows.v1.{name}") if cache else None

    def __len__(self) -> int:
        return len(self._keys)

    def keys(self) -> tuple[str, ...]:
        """The shard's HDF5 group keys, in the order the file lists them.

        Read once per shard and cached, so this costs no read. It is public
        because a record's key is the only thing that joins a shard to a split
        table keyed by record uuid, and a caller that had to reach for
        ``_keys`` would be depending on the same fact less honestly.

        Returns:
            One key per record, positionally aligned with ``self[i]``.
        """
        return self._keys

    def _index_keys(self) -> tuple[str, ...]:
        """The shard's group keys, from a sidecar when one exists.

        Listing them is not free on a shard with tens of thousands of root
        groups on a parallel filesystem: the torsion-scan shard's 83 951 keys
        took 194 s on a cold page cache (measured 2026-09-20), and every
        process that constructs this dataset — the trainer, each calibration
        subprocess — paid it again. The keys are a property of an immutable
        shard, so they are cached in a :class:`~molhub.cache.CountSidecar`
        keyed by the file's own size and mtime.

        Returns:
            One key per record, in file order.
        """
        sidecar = CountSidecar([self.path], "themol.record_keys")
        cached = sidecar.load(n_rows=None)
        if cached is not None:
            return tuple(str(key) for key in cached)
        with _open_h5(self.path) as handle:
            keys = tuple(handle.keys())
        sidecar.save(np.asarray(keys, dtype=np.str_))
        return keys

    def element_mask(self) -> np.ndarray:
        """Elements each row carries, as a bitmask, ``(N,)`` int64.

        Bit *z* is set when the row contains element *z*. One integer per row, so
        a caller can ask "which elements does this subset of rows use?" with a
        bitwise OR instead of decoding records.

        This exists because an element that a caller's *sample* never saw is the
        quietest way to corrupt a label. Fitting an atomic-reference table
        ``eps[Z]`` on a subsample leaves ``eps = 0`` for every element outside it,
        and a molecule holding one of those keeps its whole absolute-energy
        offset — order 1e6 kcal/mol — inside what is supposed to be a residual.
        Measured 2026-09-20: a table fitted on 80 THEMol records missed iodine,
        which the held-out molecules carry, and the validation mean went to
        217 162 kcal/mol against a median of 35.6. A coverage check needs the
        element sets, and this is the cheap way to have them.

        Read straight from each group's ``atomic_numbers`` — no frame is built.
        Cached in a :class:`~molhub.cache.CountSidecar`, like the other two
        per-row vectors.

        Returns:
            Bitmask per row, positionally aligned with ``self[i]``.

        Raises:
            ValueError: A record carries an element with ``Z >= 64``, which does
                not fit one integer. THEMol tops out at iodine (53); a shard that
                does not is refused rather than silently truncated.
        """
        sidecar = CountSidecar([self.path], "themol.element_mask")
        cached = sidecar.load(n_rows=len(self))
        if cached is not None:
            return np.asarray(cached, dtype=np.int64)

        masks = np.zeros(len(self), dtype=np.int64)
        handle = self._h5()
        for row, key in enumerate(self._keys):
            numbers = np.asarray(handle.array(f"{key}/atomic_numbers"), dtype=np.int64).reshape(-1)
            if numbers.size and int(numbers.max()) >= 64:
                raise ValueError(
                    f"THEMol record {key} carries element Z={int(numbers.max())}; "
                    f"element_mask packs Z < 64 into one int64 and will not truncate."
                )
            mask = 0
            for z in np.unique(numbers):
                mask |= 1 << int(z)
            masks[row] = mask
        sidecar.save(masks)
        return masks

    def molecule_index(self) -> np.ndarray:
        """Per-row molecule identity as a group index, ``(N,)`` int64.

        One row of a THEMol shard is one *scan*, and a molecule contributes as
        many scans as it has scanned dihedrals — so a split that shuffles rows
        puts the same molecule on both sides. This is the vector that prevents
        that: rows sharing a value are the same molecule, and a caller holds
        out whole groups.

        Identity is the record's ``mapped_nonisomeric_smiles``, which makes
        this **coarser** than the ``molecule_id`` a decoded frame carries —
        that one is a uuid5 of the *isomeric* SMILES, so two stereoisomers get
        two ids. Coarser is the direction a split wants: stereoisomers share a
        topology and therefore share every Class-I parameter, so training on
        one while validating on the other is leakage by another name. This can
        only merge groups a split must not separate, never split one it must
        not.

        It is also the cheap way to ask. Reading ``molecule_id`` means decoding
        a whole record — for a torsion scan, 24 frames and a SMILES parse each;
        this reads one small string per group and builds nothing. The result is
        cached in a :class:`~molhub.cache.CountSidecar`, because the first pass
        is bounded by reading the shard off a parallel filesystem once (the
        83 951-scan torsion shard: 245 s warm, and the group keys alone took
        194 s on a cold page cache).

        Returns:
            Group index per row, positionally aligned with ``self[i]``; values
            are ``0..n_molecules-1`` in first-appearance order.

        Raises:
            ValueError: A record carries no ``mapped_nonisomeric_smiles``, so
                its molecule cannot be named and no honest grouping exists.
        """
        sidecar = CountSidecar([self.path], "themol.molecule_group")
        cached = sidecar.load(n_rows=len(self))
        if cached is not None:
            return np.asarray(cached, dtype=np.int64)

        groups = np.empty(len(self), dtype=np.int64)
        seen: dict[str, int] = {}
        handle = self._h5()
        for row, key in enumerate(self._keys):
            try:
                raw = handle.array(f"{key}/mapped_nonisomeric_smiles")
            except KeyError as error:
                raise ValueError(
                    f"THEMol record {key} carries no mapped_nonisomeric_smiles, so "
                    f"its molecule cannot be identified for a group-aware split."
                ) from error
            item = raw if isinstance(raw, (str, bytes)) else np.asarray(raw).reshape(-1)[0]
            smiles = item.decode("utf-8") if isinstance(item, bytes) else str(item)
            groups[row] = seen.setdefault(smiles, len(seen))
        sidecar.save(groups)
        return groups

    @overload
    def __getitem__(self, index: int) -> Sequence[Frame]: ...

    @overload
    def __getitem__(self, index: slice) -> list[Sequence[Frame]]: ...

    def __getitem__(self, index: int | slice) -> Sequence[Frame] | list[Sequence[Frame]]:
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        return self.realize(self.stage(index))

    def stage(self, index: int) -> tuple[Any, ...]:
        """Copy record *index* off the shard, or return the cached bytes.

        A cache hit does not open the shard. The snapshot is plain numpy and
        nested dicts, so a worker thread can hand it back. Chemistry decoding
        stays in :meth:`realize`.

        Raises:
            IndexError: *index* is out of range.
        """
        idx = int(index)
        n = len(self)
        if idx < 0:
            idx += n
        if idx < 0 or idx >= n:
            raise IndexError(idx)
        if self.cache is not None:
            from molhub.cache.local import cache_write_failed

            key = int(idx).to_bytes(8, "big")
            try:
                blob = self.cache.get(key)
            except Exception as error:
                if not cache_write_failed(error):
                    raise
                self.cache = None
                blob = None
            if blob is not None and blob.startswith(b"MRFS"):
                return ("cached", blob)
        key = self._keys[idx]
        return ("source", idx, key, self._h5().snapshot(key))

    def realize(self, staged: tuple[Any, ...]) -> Sequence[Frame]:
        """Build frames for a :meth:`stage` result, on this thread."""
        from molhub.io.collection import decode_sample, encode_sample

        if staged[0] == "cached":
            return decode_sample(staged[1])
        _, idx, key, record = staged
        frames = self._reader(record, key, self.source_id)
        if self.cache is not None:
            from molhub.cache.local import cache_write_failed

            try:
                self.cache.put(int(idx).to_bytes(8, "big"), encode_sample(tuple(frames)))
            except Exception as error:
                if not cache_write_failed(error):
                    raise
                # The scratch is full. Later reads of this worker hit the shard.
                self.cache = None
        return frames

    #: What does not change over a record (molrec ``system``): the atom
    #: identity columns and the topology blocks. Everything else a frame
    #: carries is state and is written per frame.
    SYSTEM_ATOMS: tuple[str, ...] = ("element", "number", "atom_map", *TOPOLOGY_ATOM_COLUMNS)
    SYSTEM_BLOCKS: tuple[str, ...] = ("bonds", "scan")
    #: Per-frame scalars; every other meta key is the record's.
    STEP_META: tuple[str, ...] = ("energy", "step_index", "constraint_index", "torsion_angle")
    #: This reader's names -> molrec's (``docs/spec/conventions.md``).
    CONVENTION_NAMES: dict[str, str] = {
        "number": "atomic_number",
        "energy": "pe",
        "mapped_isomeric_smiles": "mapped_smiles",
    }

    def split(self, index: int) -> tuple[Frame, tuple[Frame, ...], list[int]]:
        """Record *index* as a molrec system, its frames, and their step numbers.

        The system holds :attr:`SYSTEM_ATOMS` and :attr:`SYSTEM_BLOCKS` and every
        meta key not in :attr:`STEP_META`; each frame holds the remaining
        columns and blocks and its :attr:`STEP_META` scalars. Names follow
        :attr:`CONVENTION_NAMES`. The split is declared, not inferred from what
        happens to be constant, so a one-frame record declares what a
        many-frame record does.

        Step numbers are ``step_index`` when it increases along the record,
        else ``constraint_index`` when that does, else the frame ordinal.

        Args:
            index: Record index.

        Returns:
            ``(system, frames, steps)``.
        """
        frames = tuple(self[index])
        rename = self.CONVENTION_NAMES
        first = frames[0]
        system = Frame()
        atoms = first["atoms"]
        system_atoms = {
            rename.get(name, name): np.asarray(atoms[name])
            for name in self.SYSTEM_ATOMS
            if name in atoms
        }
        if "atomic_number" in system_atoms:
            system_atoms["atomic_number"] = system_atoms["atomic_number"].astype(np.uint64)
        if "atom_map" in system_atoms:
            system_atoms["atom_map"] = system_atoms["atom_map"].astype(np.uint64)
        system["atoms"] = Block(system_atoms)
        for name in self.SYSTEM_BLOCKS:
            if name in first:
                block = first[name]
                system[name] = Block({column: np.asarray(block[column]) for column in block.keys()})
        record_meta = {k: getattr(v, "value", v) for k, v in first.meta.items()}
        system.meta = {
            rename.get(k, k): v for k, v in record_meta.items() if k not in self.STEP_META
        }
        states: list[Frame] = []
        for frame in frames:
            state = Frame()
            for name in frame.keys():
                if name in self.SYSTEM_BLOCKS:
                    continue
                block = frame[name]
                columns = {
                    column: np.asarray(block[column])
                    for column in block.keys()
                    if not (name == "atoms" and column in self.SYSTEM_ATOMS)
                }
                if columns:
                    state[name] = Block(columns)
            meta = {k: getattr(v, "value", v) for k, v in frame.meta.items()}
            state.meta = {rename.get(k, k): meta[k] for k in self.STEP_META if k in meta}
            states.append(state)
        steps = list(range(len(frames)))
        for key in ("step_index", "constraint_index"):
            values = [getattr(f.meta.get(key), "value", f.meta.get(key)) for f in frames]
            present = all(v is not None for v in values)
            if present and all(b > a for a, b in zip(values, values[1:])):
                steps = [int(v) for v in values]
                break
        return system, tuple(states), steps

    def close(self) -> None:
        """Close this thread's HDF5 handle and this process's cache."""
        store = getattr(self, "_store", None)
        if store is not None:
            store.close()
            self._store = None
        cache = getattr(self, "cache", None)
        if cache is not None:
            cache.close()

    def __getstate__(self) -> dict[str, Any]:
        state = dict(self.__dict__)
        state.pop("_store", None)
        state.pop("_lock_obj", None)
        return state

    def _h5(self) -> Any:
        store = getattr(self, "_store", None)
        if store is None:
            with instance_lock(self):
                store = getattr(self, "_store", None)
                if store is None:
                    store = self._store = _open_h5(self.path)
        return store

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def _open_h5(path: Path) -> Any:
    """Open one THEMol shard. Tests patch this name; it stays the only door."""
    try:
        from molhub.io.hdf5 import Hdf5
    except ImportError as error:
        raise ImportError(
            "Reading THEMol requires h5py; install molhub with its THEMol dependencies."
        ) from error
    return Hdf5(path, mode="r")


class _THEMolDefinition:
    COORDINATE: str
    _READER: Callable[[Any, str, str], Sequence[Frame]]

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        hub: ArtifactHub | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve() if root is not None else None
        self._hub = hub

    def load(self, role: str = "shard-000", *, cache: bool = True) -> THEMolShardDataset:
        """Fetch or locate one immutable shard and return its lazy collection.

        ``cache=False`` skips the node-local LMDB of decoded frames. A caller
        that already stores prepared rows does not want a second copy of every
        trajectory on the same scratch disk.
        """
        if not role.startswith("shard-"):
            raise ValueError(f"THEMol load expects a shard role, got {role!r}.")
        path: Path | None = None
        if self.root is not None:
            candidates = (self.root / role, self.root / f"{role}.h5")
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is None and self.root.is_file():
                path = self.root
        if path is None:
            hub = self._hub
            if hub is None:
                from molhub.molhub import Molhub

                hub = Molhub()
            path = hub.fetch(self.COORDINATE, roles=[role])[role]
        source_id = f"{self.COORDINATE}#role={role}"
        manifest = getattr(type(self), "manifest", None)
        if manifest is None:
            raise TypeError(
                f"{type(self).__name__} carries no manifest: a THEMol definition "
                "must be decorated with @dataset(...) so the dataset it loads can "
                "state its own units."
            )
        return THEMolShardDataset(
            path,
            source_id=source_id,
            reader=self._READER,
            manifest=manifest,
            cache=cache,
        )


@dataset(
    name="hessian",
    namespace="themol",
    version="1",
    description="THEMol equilibrium geometries and Cartesian Hessians.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("equilibrium", "hessian", "class-i"),
    units={"hessian": THEMOL_UNITS["hessian"]},
    blocks=("hessian",),
)
class THEMolHessian(_THEMolDefinition):
    """THEMol equilibrium geometries; one record is a length-1 ``Sequence[Frame]``.

    The Cartesian Hessian is the frame's ``hessian`` block —
    ``row``/``col``/``value``, all ``(3N)**2`` entries in row-major order — not
    a ``frame.meta`` scalar. ``TARGET_SCHEMA`` still names it ``graph_level``
    because :class:`~molhub.dataset.protocol.TargetSchema` has only the two
    layout sets; the ``blocks`` declaration that would say "block, not meta" is
    ``hf-facade-03-builder-info``'s.
    """

    COORDINATE = "dataset:themol/hessian@1"
    TARGET_SCHEMA = TargetSchema(graph_level=frozenset({"hessian"}), atom_level=frozenset())
    _READER = staticmethod(_read_hessian)


@dataset(
    name="hessian-relax",
    namespace="themol",
    version="1",
    description="THEMol Hessian-derived geometry-optimization trajectories.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("off-equilibrium", "energy", "forces", "class-i"),
    units=_ENERGY_FORCE_UNITS,
)
class THEMolHessianRelax(_THEMolDefinition):
    """THEMol relaxations; one record is one ``Sequence[Frame]``.

    Per-frame ``meta`` carries ``energy`` and ``step_index`` — the latter is
    where the deleted ``optimization_steps`` tuple went.
    """

    COORDINATE = "dataset:themol/hessian-relax@1"
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset({"energy"}), atom_level=frozenset({"forces"})
    )
    _READER = staticmethod(_read_hessian_relax)


@dataset(
    name="torsion-scan",
    namespace="themol",
    version="1",
    description="THEMol complete constrained torsion profiles.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("torsion", "profile", "class-i"),
    units={**_ENERGY_FORCE_UNITS, "torsion_angle": THEMOL_UNITS["torsion_angle"]},
)
class THEMolTorsionScan(_THEMolDefinition):
    """THEMol torsion profiles; one whole scan is one ``Sequence[Frame]``.

    Per-frame ``meta`` carries ``energy``, ``torsion_angle``, ``scan_id`` and
    ``constraint_index``; the scanned dihedral is the 1-row ``scan`` block
    (``atomi``/``atomj``/``atomk``/``atoml``), identical on every frame.
    """

    COORDINATE = "dataset:themol/torsion-scan@1"
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset({"energy", "torsion_angle"}),
        atom_level=frozenset({"forces"}),
    )
    _READER = staticmethod(_read_torsion)


@dataset(
    name="torsion-relax",
    namespace="themol",
    version="1",
    description="THEMol torsion-constrained optimization trajectories.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("off-equilibrium", "torsion", "energy", "forces", "class-i"),
    units={**_ENERGY_FORCE_UNITS, "torsion_angle": THEMOL_UNITS["torsion_angle"]},
)
class THEMolTorsionRelax(_THEMolDefinition):
    """THEMol torsion-constrained optimizations, one scan per record.

    Same shape as :class:`THEMolTorsionScan`, plus a per-frame
    ``meta["step_index"]``; frames run constraint-major, step-minor.
    """

    COORDINATE = "dataset:themol/torsion-relax@1"
    TARGET_SCHEMA = THEMolTorsionScan.TARGET_SCHEMA
    _READER = staticmethod(_read_torsion_relax)


@dataset(
    name="mbis",
    namespace="themol",
    version="1",
    description="THEMol MBIS atomic electrostatic supervision.",
    license="CC-BY-NC-4.0",
    homepage="https://huggingface.co/datasets/ByteDance-Seed/THEMol",
    citation="10.48550/arXiv.2605.14973",
    tags=("electrostatics", "mbis", "class-i"),
    units=_MBIS_UNITS,
    blocks=(_MBIS_SHELL_BLOCK,),
)
class THEMolMBIS(_THEMolDefinition):
    """THEMol MBIS supervision; one record is a length-1 ``Sequence[Frame]``.

    Every *per-atom* target is an ``atoms`` column, so ``TARGET_SCHEMA.atom_level``
    names the columns a reader will actually find on the frame:
    :data:`_MBIS_ATOM_COLUMNS` — ``atomic_charge``, ``atomic_volume``, the three
    ``dipole_<axis>`` components and the nine ``quadrupole_<axis><axis>``
    components. The grouped names it declared before dissolution
    (``atomic_dipole`` / ``atomic_quadrupole`` / ``mbis_parameters``) match no
    column of any sample, so they are gone.

    **The Slater shells are the ``mbis_shells`` block, not atom columns.** The
    source ``parameters`` array is ``(S, 3)`` — one row per MBIS Slater *shell*,
    with the shells per atom varying (H carries 1, most heavy atoms 2, a
    third-period atom can carry 3), so ``S > N`` and the rows do not line up with
    atoms at all. This reader emitted them as ``mbis_parameter_<slot>`` atom
    columns until the 2026-08-15 probe of the real published mbis ``shard-000``
    (1000 of its 430906 groups) showed that shape exists in no record: 0 of 43
    sampled indices were readable, and each column silently assigned a shell to
    whichever atom shared its row index. The block's three columns are ``atom``
    (the shell's atom index), ``population`` (in ``e`` — ``sum == Z.sum() -
    charge.sum()`` held exactly on every probed group, which is what identifies
    it as an electron population) and ``inverse_width`` (in ``angstrom^-1``,
    ``THEMOL_UNITS["inverse_sigma"]``; ~24-67 for core shells, ~3-8 for valence).

    Those two units differ, so the block declares no single ``units`` string —
    ``units`` stays the fourteen per-atom columns — and ``blocks`` is what tells
    a reader to look for ``mbis_shells`` somewhere other than ``frame.meta``.
    ``TARGET_SCHEMA`` cannot hold it either: it has only the ``graph_level`` /
    ``atom_level`` layout sets, and shell-major rows are neither.
    """

    COORDINATE = "dataset:themol/mbis@1"
    TARGET_SCHEMA = TargetSchema(
        graph_level=frozenset(),
        atom_level=frozenset(_MBIS_ATOM_COLUMNS),
    )
    _READER = staticmethod(_read_mbis)
