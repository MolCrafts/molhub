#!/usr/bin/env python
r"""Regression: one split walked a file at a time, and one split materialized.

``hf-facade-04-streaming-prepare`` gave molhub the two remaining HuggingFace
verbs — ``load_dataset(name, split=..., streaming=True)`` for a bounded-disk walk
and ``prepare(name, split=..., output_dir=...)`` for a sealed-block export — and
this script drives both through the public surface only, offline, over synthetic
shards written into a temporary directory:

* **Streaming (ac-001 / ac-002).** The train split of ``dataset:themol/mbis@1``
  is walked under a budget that can hold exactly one published file. The record
  ids, the ``take(n)`` bound, the raw-shard lifecycle the ledger records and the
  empty residency the walk leaves behind are all literals below.
* **Prepare (ac-004).** The train split of ``dataset:themol/torsion-scan@1`` is
  materialized through an **injected fake writer**, and its one sealed root, its
  unit count and its frame count are literals below.
* **Fail closed (ac-004's other half).** ``prepare("themol/mbis", ...)`` is
  refused — ``molix.block/1`` routes none of its atom-level electrostatics
  targets — with nothing created under ``output_dir``.

Determinism: no network, no clock-dependent assertion, no torch and no molnex
(asserted right after the imports and again at the end — ac-008 says *reproduces
offline with no molnex import*, and the block writer being injectable is what
makes that true rather than aspirational). ``$MOLHUB_HOME`` is *set* to the
temporary directory for the duration — the walk lands its bytes, files its
ledger and reads its split derivation under that root — and restored afterwards,
so the developer's own cache is neither read nor written.

Provenance of the goldens (hard-coded literals; nothing is recomputed here):

* The molecular identities (blake2b-128 hex of the mapped isomeric SMILES) are
  the literals ``tests/test_loader/conftest.py`` pins, themselves mirrored from
  ``tests/test_conveyor/test_prepare.py``. They are never recomputed at fixture
  time: split *production* and split *routing* drifting apart is exactly what a
  recomputed identity would hide.
  command: ``python -c "import hashlib; print(hashlib.blake2b(b'[H:1][S:2][S:3][H:4]',
  digest_size=16).hexdigest())"``; CPython 3.12, stdlib only; 2026-08-15.
* The MBIS ``parameters`` **shape and column meanings** — ``(S, 3)`` of
  ``(atom index, shell population in e, inverse Slater width in angstrom^-1)``,
  with a variable shell count per atom — come from a one-off offline probe of
  1000 groups of the real published THEMol mbis ``shard-000`` (430906 groups),
  read with h5py; date 2026-08-15. The identity ``sum(population) == Z.sum() -
  charge.sum()`` held exactly on every probed group. Nothing here reads that
  shard: ``MBIS_SHELL_ROWS`` below is synthetic and hand-derived per fixture
  molecule to satisfy the same identity, and the probe is quoted, not repeated.
  Nothing is asserted about the shells on the *read* side — they are supervision
  the walk carries, not vocabulary it uses, and their only job there is to be
  loadable. Only the water records are read back at all (hooh and hf sit in the
  splits this walk must skip), so :func:`checked_shells` validates the
  derivation on the *write* side, where every species is seen.
* The streamed ids ``mbis-a, mbis-c, mbis-d`` and the take(1) id ``mbis-a`` are
  hand-derived from the six-row split table this script writes: three train rows,
  two of them in the first shard and one in the second, so "walked on to the next
  file" is distinguishable from "re-read the file it already had".
* The lifecycle ``remote -> downloading -> ready -> consumed -> remote`` is
  :class:`~molhub.conveyor.block.BlockState`'s own string values in the order the
  ledger records them, pinned as
  ``tests/test_loader/test_streaming.py::LIFECYCLE`` pins them.
* ``TRAIN_UNITS = 3`` / ``TRAIN_FRAMES = 7`` are hand-derived from the torsion
  fixture recipe below: train scans ``scan-a``, ``scan-c``, ``scan-d`` holding 2,
  3 and 2 constrained geometries. The two numbers deliberately differ, so a check
  cannot pass by reading the other one.
* ``BLOCK_ROOT_NAME`` is ``<namespace>-<name>@<version>-<split>-<sequence>`` as
  ``molhub.conveyor.prepare.PrepareJob`` composes it, written out here as one
  literal string rather than assembled from its parts.

tool: python
command: python regressions/hf-facade-04-streaming-prepare.py
date: 2026-08-15
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import molhub  # noqa: E402
from molhub.conveyor.encoder import RawUnit  # noqa: E402
from molhub.conveyor.errors import UnsupportedRecordError  # noqa: E402
from molhub.conveyor.prepare import PreparedBlocks  # noqa: E402
from molhub.coordinate import Coordinate  # noqa: E402
from collections.abc import Sequence  # noqa: E402

from molpy import Frame  # noqa: E402

from molhub.dataset.protocol import IterableDataset  # noqa: E402
from molhub.registry import Registry  # noqa: E402
from molhub.sources.blobs import BlobStore  # noqa: E402

# ac-008's "no molnex import", made observable rather than asserted in prose: the
# loader, the conveyor and the dataset layer speak molpy and numpy, and the block
# writer is a seam, so a base install with neither torch nor molnex can stream a
# split and materialize one.
assert "torch" not in sys.modules, "importing molhub pulled torch into sys.modules"
assert "molix" not in sys.modules, "importing molhub pulled molix into sys.modules"

import h5py  # noqa: E402
import numpy as np  # noqa: E402
from molpy import Frame  # noqa: E402

# ---------------------------------------------------------------------------
# The goldens. Everything this script claims, stated before anything runs.
# ---------------------------------------------------------------------------

COORDINATE = "dataset:themol/mbis@1"
TORSION_COORDINATE = "dataset:themol/torsion-scan@1"

#: The train records of the MBIS fixture, in the order a sequential walk of the
#: two published files visits them. Two out of the first file, one out of the
#: second.
STREAMED_IDS: tuple[str, ...] = ("mbis-a", "mbis-c", "mbis-d")

#: What ``.take(n)`` is worth: three records for the whole split, and one that
#: stops *inside* the first file, before the second is ever asked for.
TAKE_3_COUNT = 3
TAKE_1_IDS: tuple[str, ...] = ("mbis-a",)

#: The other splits' records sit in the same two files and must never appear.
OTHER_SPLIT_IDS: frozenset[str] = frozenset({"mbis-b", "mbis-e", "mbis-f"})

#: The raw-shard lifecycle, in the order the ledger records it and spelled as a
#: ledger line spells it. REMOTE is declared before the fetch, DOWNLOADING is the
#: transfer's, READY is the verified local bytes, CONSUMED is exhaustion, and the
#: closing REMOTE is only true once the fetched file is gone.
LIFECYCLE: tuple[str, ...] = ("remote", "downloading", "ready", "consumed", "remote")

#: Where the conveyor keeps its bookkeeping under a molhub home — the layout
#: contract, spelled out by hand rather than asked of production.
LEDGER_SEGMENTS: tuple[str, ...] = ("conveyor", "ledger.jsonl")

#: One record's own provenance, which deliberately still names the published
#: file it came from: that is the record's traceability, not the walk's
#: vocabulary, and it is the same string the map-style path pins.
FIRST_SOURCE_ID = "dataset:themol/mbis@1#role=shard-000"

#: What the train split of the torsion fixture is worth: three scans of 2, 3 and
#: 2 constrained geometries, in the order a sequential walk visits them.
TORSION_TRAIN_KEYS: tuple[str, ...] = ("scan-a", "scan-c", "scan-d")
TRAIN_UNITS = 3
TRAIN_FRAMES = 7

#: The one sealed root that export produces, named after the pinned artifact.
BLOCK_ROOT_NAME = "themol-torsion-scan@1-train-000"
BLOCK_SPLIT = "train"

#: The block format whose missing column routes are the reason MBIS is refused.
BLOCK_FORMAT = "molix.block/1"

# ---------------------------------------------------------------------------
# Species. blake2b-128 of the mapped isomeric SMILES — see the module docstring.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Species:
    """One molecule a fixture record can be: its SMILES, geometry and identity."""

    smiles: str
    numbers: tuple[int, ...]
    coords: np.ndarray
    identity: str


WATER_IDENTITY = "810eef0a316c3ae716b15724bd6a8779"
HOOH_IDENTITY = "159fcddf7a882e2d79a52e4f129e2459"
HF_IDENTITY = "b0881071b1d54c8fb0d6817885e2a9ab"
HSSH_IDENTITY = "f534f4ca9233fbebaf8d589d560bb2e2"
HSOH_IDENTITY = "5f48010f759da2c0cf71a9a0abb616ce"

SPECIES: Mapping[str, Species] = {
    "water": Species(
        "[O:2]([H:1])[H:3]",
        (1, 8, 1),
        np.asarray([[-0.7, 0.0, 0.0], [0.0, 0.0, 0.0], [0.7, 0.0, 0.0]], dtype=np.float64),
        WATER_IDENTITY,
    ),
    "hooh": Species(
        "[H:1][O:2][O:3][H:4]",
        (1, 8, 8, 1),
        np.asarray(
            [[-1.4, 0.0, 0.0], [-0.7, 0.0, 0.0], [0.0, 0.0, 0.0], [0.7, 0.0, 0.0]],
            dtype=np.float64,
        ),
        HOOH_IDENTITY,
    ),
    "hf": Species(
        "[H:1][F:2]",
        (1, 9),
        np.asarray([[-0.7, 0.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float64),
        HF_IDENTITY,
    ),
}

#: Each MBIS species' Slater shells, as the source's ``(S, 3)`` rows ``(atom
#: index, shell population in e, inverse Slater width in angstrom^-1)``. One row
#: per *shell*, so ``S > n_atoms``: every hydrogen carries one shell and every
#: heavy atom a core and a valence shell, which is why water is 4 rows over 3
#: atoms, HOOH 6 over 4 and HF 3 over 2 — the shape no per-atom ``(N, arity)``
#: array can hold, and the reason these fixtures had to be rewritten.
#:
#: Hand-derived per molecule from the charges ``write_shard`` assigns below
#: (``0.4`` for H, ``-0.8`` otherwise), so each atom's shells sum to its own
#: population ``Z_atom - q_atom`` — H ``0.6``, O ``8.8`` as ``2.0 + 6.8``, F
#: ``9.8`` as ``2.0 + 7.8`` — and therefore the whole record satisfies the
#: probed identity ``sum(population) == Z.sum() - charge.sum()`` (10.0, 18.8 and
#: 10.4), exactly in binary floating point. The core/valence split and the
#: widths are synthetic; the shape and the identity are the probed facts (see
#: the provenance note above).
MBIS_SHELL_ROWS: Mapping[str, tuple[tuple[float, float, float], ...]] = {
    "water": ((0.0, 0.6, 3.25), (1.0, 2.0, 32.0), (1.0, 6.8, 6.75), (2.0, 0.6, 3.25)),
    "hooh": (
        (0.0, 0.6, 3.25),
        (1.0, 2.0, 32.0),
        (1.0, 6.8, 6.75),
        (2.0, 2.0, 32.0),
        (2.0, 6.8, 6.75),
        (3.0, 0.6, 3.25),
    ),
    "hf": ((0.0, 0.6, 3.25), (1.0, 2.0, 36.0), (1.0, 7.8, 7.5)),
}

#: Which HDF5 group keys each MBIS file holds, in the order h5py lists them.
SHARD_KEYS: Mapping[str, tuple[str, ...]] = {
    "shard-000": ("mbis-a", "mbis-b", "mbis-c"),
    "shard-001": ("mbis-d", "mbis-e", "mbis-f"),
}

#: Which species each MBIS record is. A species never straddles two splits, which
#: is what a molecule-level derivation guarantees and what lets the uuid-keyed and
#: identity-keyed tables below agree.
SPECIES_BY_KEY: Mapping[str, str] = {
    "mbis-a": "water",
    "mbis-b": "hooh",
    "mbis-c": "water",
    "mbis-d": "water",
    "mbis-e": "hf",
    "mbis-f": "hooh",
}

SPLIT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mbis-a", WATER_IDENTITY, "train"),
    ("mbis-b", HOOH_IDENTITY, "val"),
    ("mbis-c", WATER_IDENTITY, "train"),
    ("mbis-d", WATER_IDENTITY, "train"),
    ("mbis-e", HF_IDENTITY, "test"),
    ("mbis-f", HOOH_IDENTITY, "val"),
)

#: The four-atom species a scan record can be — a dihedral needs four atoms.
#: HOOH is shared with the MBIS fixture (same molecule, same identity, same
#: ``val``), which is what one molecule appearing in two subsets looks like.
TORSION_SPECIES: Mapping[str, Species] = {
    "hssh": Species("[H:1][S:2][S:3][H:4]", (1, 16, 16, 1), np.zeros((4, 3)), HSSH_IDENTITY),
    "hooh": Species("[H:1][O:2][O:3][H:4]", (1, 8, 8, 1), np.zeros((4, 3)), HOOH_IDENTITY),
    "hsoh": Species("[H:1][S:2][O:3][H:4]", (1, 16, 8, 1), np.zeros((4, 3)), HSOH_IDENTITY),
}

TORSION_SHARD_KEYS: Mapping[str, tuple[str, ...]] = {
    "shard-000": ("scan-a", "scan-b", "scan-c"),
    "shard-001": ("scan-d", "scan-e", "scan-f"),
}

TORSION_SPECIES_BY_KEY: Mapping[str, str] = {
    "scan-a": "hssh",
    "scan-b": "hooh",
    "scan-c": "hssh",
    "scan-d": "hssh",
    "scan-e": "hsoh",
    "scan-f": "hooh",
}

#: How many constrained geometries each scan holds — its frame count. Deliberately
#: unequal, so a split's frame count is not its unit count times a constant.
TORSION_CONSTRAINTS: Mapping[str, int] = {
    "scan-a": 2,
    "scan-b": 2,
    "scan-c": 3,
    "scan-d": 2,
    "scan-e": 1,
    "scan-f": 2,
}

TORSION_SPLIT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("scan-a", HSSH_IDENTITY, "train"),
    ("scan-b", HOOH_IDENTITY, "val"),
    ("scan-c", HSSH_IDENTITY, "train"),
    ("scan-d", HSSH_IDENTITY, "train"),
    ("scan-e", HSOH_IDENTITY, "test"),
    ("scan-f", HOOH_IDENTITY, "val"),
)

#: The published derivation, its filenames and where it lives under a home. The
#: torsion table carries no ``_uuid_`` — that irregularity is the producer's, and
#: restating it here is what keeps a wrong guess visible.
SPLIT_COORDINATE = "dataset:molcrafts/class1-universal-splits@1"
UUID_FILENAME = "mbis_uuid_splits.csv.gz"
TORSION_UUID_FILENAME = "torsion_scan_splits.csv.gz"
IDENTITY_FILENAME = "identity_splits.csv.gz"
SPLIT_SUBPATH: tuple[str, ...] = ("derived", "molcrafts", "class1-universal-splits", "1")

INDEX_SIZE = 101

DESCRIPTION = "THEMol MBIS atomic electrostatic supervision."
LICENSE = "CC-BY-NC-4.0"
CITATION = "10.48550/arXiv.2605.14973"

#: The provenance ``molix.block/1`` requires, stated by this script so the export
#: under test never reaches for a clock.
PROVENANCE: Mapping[str, object] = {
    "source": TORSION_COORDINATE,
    "generator": "regressions/hf-facade-04-streaming-prepare.py",
    "created_at": "2026-08-15T00:00:00Z",
    "units": {"coordinates": "angstrom"},
}


# ---------------------------------------------------------------------------
# Fixture construction — synthetic THEMol HDF5 files, a registry that declares
# their real bytes, and the miniature split derivation that assigns them.
# ---------------------------------------------------------------------------


def torsion_coords(shift: float) -> np.ndarray:
    """One geometry of a scanned four-atom chain, twisted by *shift*."""
    return np.asarray(
        [[-1.0, 1.0, shift], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 1.0, 1.0 + shift]],
        dtype=np.float64,
    )


def checked_shells(name: str, numbers: Sequence[int], charges: np.ndarray) -> np.ndarray:
    """The hand-derived shell table of species *name*, checked before it is written.

    Only the water records of this fixture are ever read back — hooh and hf sit
    in the ``val`` and ``test`` splits the train walk must skip — so a wrong
    literal for those two would be written, never loaded, and never noticed.
    The derivation is therefore checked here, for every record written: the
    three properties :func:`~molhub.dataset.themol._read_mbis` enforces (an
    ``(S, 3)`` table, integral in-range atom indices, no atom without a shell)
    plus the two identities those literals were derived from, which the reader
    does not check and which are what make the populations meaningful rather
    than arbitrary: every atom's shells sum to its own population ``Z_atom -
    q_atom``, and therefore the record's shells sum to its electron count
    ``Z.sum() - charge.sum()`` — the probed identity. The per-atom form is the
    load-bearing one: moving one atom's shell onto another leaves the range, the
    coverage and the total all intact. This validates the *fixture*, not
    production.
    """
    shells = np.asarray(MBIS_SHELL_ROWS[name], dtype=np.float64)
    n_atoms = len(numbers)
    assert shells.ndim == 2 and shells.shape[1] == 3, (
        f"{name}: shells are (S, 3), got {shells.shape}"
    )
    atom = shells[:, 0]
    assert (atom == np.trunc(atom)).all(), f"{name}: a shell atom index is not integral"
    assert atom.min() >= 0.0 and atom.max() < n_atoms, (
        f"{name}: a shell addresses no atom of [0, {n_atoms})"
    )
    counts = np.bincount(atom.astype(np.int64), minlength=n_atoms)
    assert counts.all(), f"{name}: atom(s) {np.flatnonzero(counts == 0).tolist()} carry no shell"
    index = atom.astype(np.int64)
    per_atom = [float(shells[index == i, 1].sum()) for i in range(n_atoms)]
    expected = [float(numbers[i]) - float(charges[i, 0]) for i in range(n_atoms)]
    assert per_atom == expected, (
        f"{name}: an atom's shells sum to {per_atom}, not its own population "
        f"Z_atom - q_atom = {expected}"
    )
    electrons = float(np.asarray(numbers, dtype=np.int64).sum()) - float(charges.sum())
    assert float(shells[:, 1].sum()) == electrons, (
        f"{name}: shell populations sum to {float(shells[:, 1].sum())}, not the record's "
        f"{electrons} electrons"
    )
    return shells


def write_shard(path: Path, keys: Sequence[str]) -> Path:
    """Write a THEMol MBIS file holding one record per key in *keys*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    string = h5py.string_dtype("utf-8")
    with h5py.File(path, "w") as handle:
        for key in keys:
            species = SPECIES[SPECIES_BY_KEY[key]]
            n_atoms = len(species.numbers)
            charges = np.asarray(
                [[0.4 if number == 1 else -0.8] for number in species.numbers], dtype=np.float64
            )
            shells = checked_shells(SPECIES_BY_KEY[key], species.numbers, charges)
            group = handle.create_group(key)
            group.create_dataset("mapped_nonisomeric_smiles", data=species.smiles, dtype=string)
            group.create_dataset("mapped_isomeric_smiles", data=species.smiles, dtype=string)
            group.create_dataset(
                "atomic_numbers", data=np.asarray(species.numbers, dtype=np.int32)[:, None]
            )
            group.create_dataset("coords", data=species.coords)
            info = group.create_group("mbis_info")
            info.create_dataset("atomic_volumes", data=np.ones((n_atoms, 1)))
            info.create_dataset("atomic_charge", data=charges)
            info.create_dataset("atomic_dipole", data=np.ones((n_atoms, 3)))
            info.create_dataset("atomic_quadrupole", data=np.ones((n_atoms, 3, 3)))
            group.create_dataset("parameters", data=shells)
    return path


def write_torsion_shard(path: Path, keys: Sequence[str]) -> Path:
    """Write a THEMol torsion-scan file holding one whole scan per key in *keys*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    string = h5py.string_dtype("utf-8")
    with h5py.File(path, "w") as handle:
        for key in keys:
            species = TORSION_SPECIES[TORSION_SPECIES_BY_KEY[key]]
            group = handle.create_group(key)
            group.create_dataset("mapped_nonisomeric_smiles", data=species.smiles, dtype=string)
            group.create_dataset("mapped_isomeric_smiles", data=species.smiles, dtype=string)
            group.create_dataset(
                "atomic_numbers", data=np.asarray(species.numbers, dtype=np.int32)[:, None]
            )
            group.create_dataset("torsion_atom_indices", data=np.arange(4, dtype=np.int32))
            for index in range(TORSION_CONSTRAINTS[key]):
                coords = torsion_coords(float(index))
                constraint = group.create_group(f"constraint {index}")
                constraint.create_dataset("coords", data=coords)
                constraint.create_dataset("energy", data=np.asarray(-1.0 - index))
                constraint.create_dataset("forces", data=np.full_like(coords, 0.5 * index))
    return path


def verified_manifest_yaml(files: Mapping[str, Path], *, name: str, title: str) -> str:
    """A manifest declaring the real size and sha256 of every file in *files*.

    A streaming walk re-verifies both against the manifest and deletes anything
    that disagrees, so its fixture manifest has to state the truth about the
    files on disk — unlike the map-style fixtures, which verify nothing and can
    afford three distinctive fake sizes.
    """
    stem = name.replace("-", "_")
    artifacts = "".join(
        f"  - role: {role}\n"
        f"    filename: {stem}_{index}.h5\n"
        f"    format: hdf5\n"
        f'    digest: "sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"\n'
        f"    size: {path.stat().st_size}\n"
        f"    locators:\n"
        f"      - fake://{stem}-{index}\n"
        for index, (role, path) in enumerate(files.items())
    )
    return (
        "schema_version: 1\n"
        "kind: dataset\n"
        "namespace: themol\n"
        f"name: {name}\n"
        'version: "1"\n'
        "\n"
        f"title: {title}\n"
        f'description: "{DESCRIPTION}"\n'
        f"license: {LICENSE}\n"
        f"doi: {CITATION}\n"
        "\n"
        "artifacts:\n"
        "  - role: index\n"
        f"    filename: {stem}_dataset.csv\n"
        "    format: csv\n"
        f"    size: {INDEX_SIZE}\n"
        "    locators:\n"
        f"      - fake://{stem}-index\n"
        f"{artifacts}"
    )


def build_verified_registry(
    root: Path, files: Mapping[str, Path], *, name: str, title: str
) -> Registry:
    """Write and load a registry whose declared bytes are *files*' real bytes."""
    path = root / "dataset" / "themol" / name / "1.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(verified_manifest_yaml(files, name=name, title=title), encoding="utf-8")
    return Registry.load(root)


def _write_rows(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write one gzipped CSV exactly as ``scripts/build_class1_splits.py`` does."""
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(header))
        for row in rows:
            writer.writerow(list(row))


def write_split_derivation(root: Path) -> Path:
    """Write a provenance-consistent miniature ``class1-universal-splits/1/``.

    Both uuid-keyed tables are written — one per fixture dataset — beside the
    single molecule-level table they were folded from, which is the shape the
    real derivation has: one directory, one seed, one answer per molecule.
    """
    root.mkdir(parents=True, exist_ok=True)
    _write_rows(root / UUID_FILENAME, ("uuid", "identity", "split"), SPLIT_ROWS)
    _write_rows(root / TORSION_UUID_FILENAME, ("uuid", "identity", "split"), TORSION_SPLIT_ROWS)
    folded = {identity: split for _, identity, split in (*SPLIT_ROWS, *TORSION_SPLIT_ROWS)}
    _write_rows(root / IDENTITY_FILENAME, ("identity", "split"), folded.items())
    metadata = {
        "coordinate": SPLIT_COORDINATE,
        "seed": 20260814,
        "ratios": "8:1:1 train:val:test, molecule level",
        "generator": "scripts/build_class1_splits.py",
        "output_sha256": {
            filename: hashlib.sha256((root / filename).read_bytes()).hexdigest()
            for filename in (UUID_FILENAME, TORSION_UUID_FILENAME, IDENTITY_FILENAME)
        },
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return root


class LandingHub:
    """An ``ArtifactHub`` that **lands** its bytes where the fetcher would.

    A hub handing back the pristine fixture file would have the walk delete the
    fixture, and the second visit would find nothing to serve. This one copies
    the pristine bytes to ``$MOLHUB_HOME/files/<coordinate>/<role>`` and returns
    that path, so deleting it is exactly the rolling delete under test and a
    re-fetch genuinely re-lands the bytes.

    Args:
        files: Role to the pristine file whose bytes that role serves. These are
            never handed out and never deleted.
        home: The molhub home the cache sits under.
        coordinate: The artifact whose roles these are.
    """

    def __init__(self, files: Mapping[str, Path], *, home: Path, coordinate: str) -> None:
        self._files = dict(files)
        self._store = BlobStore(home)
        self._coordinate = Coordinate.parse(coordinate)
        self.roles_fetched: list[str] = []

    def cache_path(self, role: str) -> Path:
        """Where role *role*'s bytes live once fetched — the fetcher's own key."""
        return self._store.path_for(f"{self._coordinate.cache_path()}/{role}")

    def resident(self) -> tuple[str, ...]:
        """The roles whose cache file exists right now, in manifest order."""
        return tuple(role for role in self._files if self.cache_path(role).is_file())

    def resident_bytes(self) -> int:
        """How many bytes of fetched-and-not-yet-deleted files are on disk."""
        return sum(self.cache_path(role).stat().st_size for role in self.resident())

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Land every requested role at its cache path and return the cache paths."""
        requested = tuple(roles) if roles is not None else tuple(self._files)
        missing = [role for role in requested if role not in self._files]
        if missing:
            raise KeyError(f"{coordinate} has no role {missing}")
        self.roles_fetched.extend(requested)
        landed: dict[str, Path] = {}
        for role in requested:
            target = self.cache_path(role)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self._files[role].read_bytes())
            landed[role] = target
        return landed


class FakeBlockWriter:
    """A ``BlockWriterLike`` that records what it took and seals honestly.

    Honest about the one thing molhub reads back — on :meth:`seal` it writes the
    five manifest fields ``PrepareJob`` verifies — so the export's own checks run
    for real without torch or molnex anywhere near this process.

    Args:
        root: Block directory; created on construction, as the real writer does.
        split: The one split this block holds — a constructor argument, never a
            per-unit field.
        provenance: Opaque provenance mapping, recorded for inspection.
        digest: The ``block_digest`` this fake writes on :meth:`seal`.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        split: str,
        provenance: Mapping[str, object],
        digest: str = f"{0:064x}",
    ) -> None:
        self.root = Path(root)
        self.split = split
        self.provenance = dict(provenance)
        self.digest = digest
        self.appended: list[RawUnit] = []
        self._bytes = 0
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def unit_count(self) -> int:
        """Units committed to this block so far."""
        return len(self.appended)

    @property
    def committed_bytes(self) -> int:
        """Committed column payload in bytes."""
        return self._bytes

    @property
    def keys(self) -> tuple[str, ...]:
        """The unit key of every unit this block took, in arrival order."""
        return tuple(unit.key for unit in self.appended)

    @property
    def identities(self) -> tuple[str, ...]:
        """The molecular identity of every unit this block took, in arrival order."""
        return tuple(unit.identity for unit in self.appended)

    def append_unit(self, unit: RawUnit) -> int:
        """Append one whole sampling unit and return its index."""
        self.appended.append(unit)
        self._bytes += sum(
            column.nbytes for column in (*unit.topology.values(), *unit.frames.values())
        )
        return len(self.appended) - 1

    def seal(self) -> None:
        """Finalize the block by writing the manifest molhub reads back."""
        if not self.appended:
            raise ValueError(f"block at {self.root} has no units; molnex rejects an empty seal")
        (self.root / "manifest.json").write_text(
            json.dumps(
                {
                    "format": BLOCK_FORMAT,
                    "split": self.split,
                    "units": self.unit_count,
                    "sealed": True,
                    "block_digest": self.digest,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


class RecordingWriterFactory:
    """A ``BlockWriterFactory`` — the *constructor* seam, with a log."""

    def __init__(self) -> None:
        self.writers: list[FakeBlockWriter] = []

    def __call__(
        self, root: Path, *, split: str, provenance: Mapping[str, object]
    ) -> FakeBlockWriter:
        """Open a writer for one block at *root* holding exactly one *split*."""
        writer = FakeBlockWriter(
            root, split=split, provenance=provenance, digest=f"{len(self.writers):064x}"
        )
        self.writers.append(writer)
        return writer

    @property
    def splits(self) -> tuple[str, ...]:
        """The split every writer was opened for, in the order they were opened."""
        return tuple(writer.split for writer in self.writers)


# ---------------------------------------------------------------------------
# Readers over what the walk left behind.
# ---------------------------------------------------------------------------


def _ids(records: Iterable[Sequence[Frame]]) -> tuple[str, ...]:
    """The ``source_record_id`` of every record of an iterable, in walk order."""
    return tuple(str(record[0].meta["source_record_id"]) for record in records)


def _ledger_text(path: Path) -> str:
    """The conveyor ledger file's text, or ``""`` when nothing wrote one yet."""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _lifecycle(text: str) -> dict[str, tuple[str, ...]]:
    """Every transition the ledger's JSONL records, per file, in file order.

    Read back off the file rather than through :class:`~molhub.conveyor.Ledger`:
    what is pinned is what a second process would see on disk, and a reader that
    folded the lines through the same type that wrote them could agree with a
    file nobody else can read.

    The ledger is append-only and outlives one walk, so every check below reads
    the slice **one** walk appended (``text[len(before):]``) rather than the whole
    file: a lifecycle that repeats because two walks ran is not a lifecycle that
    happened twice in one.
    """
    states: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        columns = json.loads(line)
        if columns.get("record") != "transition":
            continue
        states.setdefault(str(columns["block_id"]), []).append(str(columns["state"]))
    return {block: tuple(recorded) for block, recorded in states.items()}


# ---------------------------------------------------------------------------
# Leg 1 — the whole train split, walked one published file at a time
# ---------------------------------------------------------------------------


def check_streaming_walk(registry: Registry, hub: LandingHub, ledger: Path, budget: int) -> None:
    """ac-001 + ac-002: the pinned ids, the pinned lifecycle, nothing left behind."""
    before = _ledger_text(ledger)
    stream = molhub.load(
        "themol/mbis",
        split="train",
        streaming=True,
        disk_budget=budget,
        registry=registry,
        hub=hub,
    )
    assert isinstance(stream, IterableDataset), type(stream)

    records = list(stream)
    assert all(isinstance(record[0], Frame) for record in records), [type(r) for r in records]

    walked = _ids(records)
    assert walked == STREAMED_IDS, walked
    assert set(walked).isdisjoint(OTHER_SPLIT_IDS), walked

    # One meta literal: a record still names the published file it came from.
    assert records[0][0].meta["source_id"] == FIRST_SOURCE_ID, records[0][0].meta["source_id"]

    recorded = _lifecycle(_ledger_text(ledger)[len(before) :])
    assert recorded == {"shard-000": LIFECYCLE, "shard-001": LIFECYCLE}, recorded

    assert hub.roles_fetched == ["shard-000", "shard-001"], hub.roles_fetched
    assert hub.resident() == (), hub.resident()
    assert hub.resident_bytes() == 0, hub.resident_bytes()

    print(
        f"  Streaming: {len(walked)} records {walked} under a {budget}-byte budget, "
        f"lifecycle {LIFECYCLE} for both published files, nothing resident afterwards"
    )


# ---------------------------------------------------------------------------
# Leg 2 — the same walk, bounded by `.take(n)`
# ---------------------------------------------------------------------------


def check_take_bounds_the_walk(
    registry: Registry, hub: LandingHub, ledger: Path, budget: int
) -> None:
    """ac-001 + ac-002: ``take`` yields that many records and stops where it says."""

    def stream() -> IterableDataset[Frame]:
        return cast(
            "IterableDataset[Frame]",
            molhub.load(
                "themol/mbis",
                split="train",
                streaming=True,
                disk_budget=budget,
                registry=registry,
                hub=hub,
            ),
        )

    before = _ledger_text(ledger)
    whole = list(stream().take(TAKE_3_COUNT))
    assert len(whole) == TAKE_3_COUNT == 3, len(whole)
    assert _ids(whole) == STREAMED_IDS, _ids(whole)
    bounded = _lifecycle(_ledger_text(ledger)[len(before) :])
    assert bounded == {"shard-000": LIFECYCLE, "shard-001": LIFECYCLE}, bounded

    before = _ledger_text(ledger)
    fetched_so_far = len(hub.roles_fetched)
    early = list(stream().take(1))
    assert _ids(early) == TAKE_1_IDS, _ids(early)

    # ``mbis-a`` is the first of two train rows in the first file, so this stops
    # *inside* it: the second file is never asked for, and the first is released
    # anyway — an early exit is not a leak.
    assert hub.roles_fetched[fetched_so_far:] == ["shard-000"], hub.roles_fetched
    assert hub.resident() == (), hub.resident()
    stopped = _lifecycle(_ledger_text(ledger)[len(before) :])
    assert stopped == {"shard-000": LIFECYCLE}, stopped

    print(
        f"  take: take({TAKE_3_COUNT}) -> {len(whole)} records {_ids(whole)}, take(1) -> "
        f"{TAKE_1_IDS} fetching only the file that owns it"
    )


# ---------------------------------------------------------------------------
# Leg 3 — one split materialized as sealed blocks, through an injected writer
# ---------------------------------------------------------------------------


def check_prepare_seals_one_split(
    registry: Registry, hub: LandingHub, output_dir: Path
) -> PreparedBlocks:
    """ac-004: three whole scans, seven constrained geometries, one sealed root."""
    factory = RecordingWriterFactory()
    prepared = molhub.prepare(
        "themol/torsion-scan",
        split="train",
        output_dir=output_dir,
        registry=registry,
        hub=hub,
        writer_factory=factory,
        provenance=PROVENANCE,
    )
    assert isinstance(prepared, PreparedBlocks), type(prepared)

    assert len(prepared.blocks) == 1, prepared.blocks
    block = prepared.blocks[0]
    assert block.split == BLOCK_SPLIT, block.split
    assert block.unit_count == TRAIN_UNITS == 3, block.unit_count
    assert block.frame_count == TRAIN_FRAMES == 7, block.frame_count

    assert block.root.is_dir(), block.root
    assert block.root.parent == output_dir, block.root
    assert block.root.name == BLOCK_ROOT_NAME, block.root.name
    assert [path.name for path in output_dir.iterdir()] == [BLOCK_ROOT_NAME], sorted(
        path.name for path in output_dir.iterdir()
    )

    # Only the requested split's writer was ever opened, and every unit that
    # reached it is a whole scan of the train molecule.
    writer = factory.writers[0]
    assert factory.splits == (BLOCK_SPLIT,), factory.splits
    assert writer.keys == TORSION_TRAIN_KEYS, writer.keys
    assert writer.identities == (HSSH_IDENTITY,) * TRAIN_UNITS, writer.identities

    print(
        f"  prepare: one sealed root {BLOCK_ROOT_NAME!r} under {output_dir.name}/, "
        f"unit_count {block.unit_count} (whole scans) and frame_count {block.frame_count} "
        f"(2 + 3 + 2 constrained geometries), split {block.split!r}"
    )
    return prepared


# ---------------------------------------------------------------------------
# Leg 4 — a dataset `molix.block/1` has no routes for is refused, not exported
# ---------------------------------------------------------------------------


def check_prepare_refuses_unroutable_targets(
    registry: Registry, hub: LandingHub, output_dir: Path
) -> None:
    """ac-004's other half: fail closed, with nothing created under *output_dir*."""
    assert not output_dir.exists(), output_dir
    factory = RecordingWriterFactory()
    try:
        molhub.prepare(
            "themol/mbis",
            split="train",
            output_dir=output_dir,
            registry=registry,
            hub=hub,
            writer_factory=factory,
            provenance=PROVENANCE,
        )
    except UnsupportedRecordError as error:
        message = str(error)
        assert "RawUnit" in message, message
        assert COORDINATE in message, message
        assert "drop" in message.lower(), message
    else:  # pragma: no cover - the refusal is the point of this leg
        raise AssertionError("prepare('themol/mbis', ...) exported a dataset it cannot route")

    # An injected writer is not the question — the targets are — so the refusal
    # has to come before anything is opened, created or fetched.
    assert factory.writers == [], factory.writers
    assert not output_dir.exists(), output_dir
    assert hub.roles_fetched == [], hub.roles_fetched

    print(
        "  prepare/refusal: themol/mbis raises UnsupportedRecordError naming RawUnit, "
        f"with no writer opened, nothing fetched and {output_dir.name}/ never created"
    )


# ---------------------------------------------------------------------------
# Leg 5 — the whole of the above, in an install with neither torch nor molnex
# ---------------------------------------------------------------------------


def check_nothing_imported_molnex() -> None:
    """ac-008: streaming and prepare ran offline, torch-free and molnex-free."""
    assert "torch" not in sys.modules, "the streaming/prepare path pulled torch in"
    assert "molix" not in sys.modules, "the streaming/prepare path pulled molix in"
    print("  Offline: neither torch nor molix reached sys.modules on either path")


def main() -> None:
    """Build both fixture datasets in a temporary directory and check them."""
    with tempfile.TemporaryDirectory(prefix="molhub-hf-facade-04-") as workdir:
        root = Path(workdir)
        home = root / "home"
        write_split_derivation(home.joinpath(*SPLIT_SUBPATH))
        ledger = home.joinpath(*LEDGER_SEGMENTS)

        pristine = {
            role: write_shard(root / "pristine" / f"{role}.h5", keys)
            for role, keys in SHARD_KEYS.items()
        }
        pristine_torsion = {
            role: write_torsion_shard(root / "pristine-torsion" / f"{role}.h5", keys)
            for role, keys in TORSION_SHARD_KEYS.items()
        }
        registry = build_verified_registry(
            root / "registry", pristine, name="mbis", title="THEMol MBIS atomic electrostatics"
        )
        torsion_registry = build_verified_registry(
            root / "torsion-registry",
            pristine_torsion,
            name="torsion-scan",
            title="THEMol constrained torsion profiles",
        )
        # A budget that admits one published file and can never admit two.
        budget = max(path.stat().st_size for path in pristine.values()) + 1

        previous = os.environ.get("MOLHUB_HOME")
        os.environ["MOLHUB_HOME"] = str(home)
        try:
            check_streaming_walk(
                registry, LandingHub(pristine, home=home, coordinate=COORDINATE), ledger, budget
            )
            check_take_bounds_the_walk(
                registry, LandingHub(pristine, home=home, coordinate=COORDINATE), ledger, budget
            )
            check_prepare_seals_one_split(
                torsion_registry,
                LandingHub(pristine_torsion, home=home, coordinate=TORSION_COORDINATE),
                root / "blocks",
            )
            check_prepare_refuses_unroutable_targets(
                registry,
                LandingHub(pristine, home=home, coordinate=COORDINATE),
                root / "refused-blocks",
            )
            check_nothing_imported_molnex()
        finally:
            if previous is None:
                os.environ.pop("MOLHUB_HOME", None)
            else:
                os.environ["MOLHUB_HOME"] = previous

    print("hf-facade-04-streaming-prepare: OK")


if __name__ == "__main__":
    main()
