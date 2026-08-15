"""Shared fixtures for the loader tests — one synthetic THEMol dataset, no network.

What ``tests/test_conveyor/conftest.py`` is to the conveyor, this is to the
loader: every byte a loader test reads is written into ``tmp_path`` here, so no
test depends on ``$MOLHUB_HOME`` as the developer happens to have it, on the
bundled registry snapshot, or on the real THEMol shards — 28.9 GiB for MBIS,
5.9 TiB for the whole collection.

**Nothing here imports ``molhub.loader`` or ``molhub.conveyor.splits``.** The
first does not exist yet and the second is mid-rename (``SplitTable`` ->
``_SplitTable``); a conftest that imported either would turn every test in this
package — including ``test_layering.py``, which is answerable today — into one
collection error instead of failures with names on them.

The fixture dataset is ``dataset:themol/mbis@1`` in miniature: two shards of
three records each, and the miniature ``class1-universal-splits@1`` derivation
that assigns them. The rows are chosen so that

* the three splits have three *different* counts (train 3, val 2, test 1), so a
  test cannot pass by reading the wrong split's number, and
* one shard holds two train rows while the other holds one, which is the only
  arrangement that can tell "walked on to the next shard" apart from "re-read
  the shard it already had".

**Three species, and why the two split tables agree** (added for
``hf-facade-04-streaming-prepare``). A split is assigned per *record uuid* in
``mbis_uuid_splits.csv.gz`` and per *molecular identity* in
``identity_splits.csv.gz``, and the prepare stage routes by the second while a
split view filters by the first. Six water records would carry **one** identity
between them, so no per-uuid assignment could agree with any per-identity one
and every prepare test would die in ``UnroutableUnitError`` for a reason that
says nothing about the code under test. So each record is one of three species
— water, hydrogen peroxide, hydrogen fluoride — assigned so that a species is
never split across two splits (:data:`SPECIES_BY_KEY`), which is what a real
molecule-level derivation guarantees. The split counts, the train keys and the
shard membership are unchanged by that; ``mbis-a``, ``mbis-c`` and ``mbis-d``
— the whole train split — are still water.

**A second fixture dataset: ``dataset:themol/torsion-scan@1``.** ``prepare``
refuses a dataset whose targets ``molix.block/1`` routes none of — which is
exactly what MBIS is — so the fixture above can only demonstrate that refusal,
never a successful export. The torsion-scan fixture is the routable counterpart:
every target of a scan (``pos``, ``energy``, ``forces``, ``torsion_angle`` and
the scanned dihedral) has a column route, so a successful materialization is
observable without asking the export to drop anything. It is built the same way
— two shards, six records, three species, train 3 / val 2 / test 1 — with two
deliberate differences:

* one record is one *whole scan*, so units and frames no longer coincide: the
  train split is 3 units and 7 frames (:data:`TORSION_CONSTRAINTS`), and a test
  reading the wrong one of those two numbers fails.
* a dihedral needs four atoms, so its species are four-atom chains — HSSH,
  HOOH, HSOH. HOOH is shared with the MBIS fixture (same molecule, same
  identity, same ``val``), which is what a molecule-level derivation spanning
  two subsets looks like.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import tarfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import pytest

from molhub.conveyor.tier import DerivedLayout
from molhub.coordinate import Coordinate
from molhub.registry import Registry
from molhub.sources.blobs import BlobStore

# ---------------------------------------------------------------------------
# The fixture dataset: two shards of dataset:themol/mbis@1.
# ---------------------------------------------------------------------------

COORDINATE = "dataset:themol/mbis@1"

#: Atom-map order H:1, O:2, H:3 — deliberately unlike SMILES parse order, the
#: same water record ``tests/test_dataset/test_themol.py`` reads.
WATER = "[O:2]([H:1])[H:3]"
WATER_NUMBERS: tuple[int, ...] = (1, 8, 1)
WATER_COORDS = np.asarray([[-0.7, 0.0, 0.0], [0.0, 0.0, 0.0], [0.7, 0.0, 0.0]], dtype=np.float64)


@dataclass(frozen=True)
class Species:
    """One molecule a fixture record can be: its mapped SMILES and its geometry.

    Attributes:
        smiles: Atom-mapped isomeric SMILES, with the map ids exactly ``1..N``
            — what ``THEMolShardDataset`` parses the topology out of.
        numbers: Atomic numbers in atom-map order, which the reader cross-checks
            against the parsed SMILES.
        coords: ``(N, 3)`` positions, on a line and 0.7 Å apart.
        identity: blake2b-128 of :attr:`smiles` — the molecular identity the
            prepare stage routes by. A pinned literal, mirrored from
            ``tests/test_conveyor/test_prepare.py``, never computed here: split
            *production* and split *routing* drifting apart is exactly what a
            recomputed identity would hide.
    """

    smiles: str
    numbers: tuple[int, ...]
    coords: np.ndarray
    identity: str


#: blake2b-128 of each mapped SMILES; see :class:`Species`.
WATER_IDENTITY = "810eef0a316c3ae716b15724bd6a8779"
HOOH_IDENTITY = "159fcddf7a882e2d79a52e4f129e2459"
HF_IDENTITY = "b0881071b1d54c8fb0d6817885e2a9ab"

#: The three species a fixture record can be, by short name.
SPECIES: Mapping[str, Species] = {
    "water": Species(WATER, WATER_NUMBERS, WATER_COORDS, WATER_IDENTITY),
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

#: Which HDF5 group keys each shard holds, in the order h5py lists them.
SHARD_KEYS: Mapping[str, tuple[str, ...]] = {
    "shard-000": ("mbis-a", "mbis-b", "mbis-c"),
    "shard-001": ("mbis-d", "mbis-e", "mbis-f"),
}

#: Which species each record is. One species never straddles two splits, so the
#: uuid-keyed and identity-keyed tables below assign the same thing — see the
#: module docstring. A key absent from here is water.
SPECIES_BY_KEY: Mapping[str, str] = {
    "mbis-a": "water",
    "mbis-b": "hooh",
    "mbis-c": "water",
    "mbis-d": "water",
    "mbis-e": "hf",
    "mbis-f": "hooh",
}

#: ``uuid, identity, split`` rows of the miniature split derivation. Train rows
#: land in both shards, two of them in the first.
SPLIT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mbis-a", WATER_IDENTITY, "train"),
    ("mbis-b", HOOH_IDENTITY, "val"),
    ("mbis-c", WATER_IDENTITY, "train"),
    ("mbis-d", WATER_IDENTITY, "train"),
    ("mbis-e", HF_IDENTITY, "test"),
    ("mbis-f", HOOH_IDENTITY, "val"),
)

#: What ``_SplitTable.counts()`` folds out of :data:`SPLIT_ROWS`.
SPLIT_COUNTS: Mapping[str, int] = {"train": 3, "val": 2, "test": 1}

#: The train rows in the order a sequential walk of the shards visits them.
TRAIN_KEYS: tuple[str, ...] = ("mbis-a", "mbis-c", "mbis-d")

# ---------------------------------------------------------------------------
# The second fixture dataset: two shards of dataset:themol/torsion-scan@1, the
# routable counterpart of the one above. See the module docstring.
# ---------------------------------------------------------------------------

TORSION_COORDINATE = "dataset:themol/torsion-scan@1"

#: blake2b-128 of each mapped SMILES, computed once with
#: ``THEMolUnitEncoder.identity`` and pinned here as literals — never recomputed
#: at fixture time, for the reason :class:`Species` states.
HSSH_IDENTITY = "f534f4ca9233fbebaf8d589d560bb2e2"
HSOH_IDENTITY = "5f48010f759da2c0cf71a9a0abb616ce"


def torsion_coords(shift: float) -> np.ndarray:
    """One geometry of the scanned four-atom chain, twisted by *shift*.

    The same shape ``tests/test_dataset/test_themol.py`` scans over: a central
    bond along x with the two end atoms off it, so the dihedral about
    ``(0, 1, 2, 3)`` is defined (a zero-length central bond is refused by the
    reader) and moves with *shift*.

    Args:
        shift: How far the two end atoms are displaced along z; one constraint
            index, one shift.

    Returns:
        ``(4, 3)`` positions in atom-map order.
    """
    return np.asarray(
        [
            [-1.0, 1.0, shift],
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 1.0, 1.0 + shift],
        ],
        dtype=np.float64,
    )


#: The three four-atom species a scan record can be. ``coords`` is the
#: constraint-0 geometry; a scan's real geometries are per-constraint and come
#: from :func:`torsion_coords`.
TORSION_SPECIES: Mapping[str, Species] = {
    "hssh": Species("[H:1][S:2][S:3][H:4]", (1, 16, 16, 1), torsion_coords(0.0), HSSH_IDENTITY),
    "hooh": Species("[H:1][O:2][O:3][H:4]", (1, 8, 8, 1), torsion_coords(0.0), HOOH_IDENTITY),
    "hsoh": Species("[H:1][S:2][O:3][H:4]", (1, 16, 8, 1), torsion_coords(0.0), HSOH_IDENTITY),
}

#: Which HDF5 group keys each torsion shard holds, in the order h5py lists them.
TORSION_SHARD_KEYS: Mapping[str, tuple[str, ...]] = {
    "shard-000": ("scan-a", "scan-b", "scan-c"),
    "shard-001": ("scan-d", "scan-e", "scan-f"),
}

#: Which species each scan is, in the same per-shard arrangement as
#: :data:`SPECIES_BY_KEY`: two train rows in the first shard, one in the second.
TORSION_SPECIES_BY_KEY: Mapping[str, str] = {
    "scan-a": "hssh",
    "scan-b": "hooh",
    "scan-c": "hssh",
    "scan-d": "hssh",
    "scan-e": "hsoh",
    "scan-f": "hooh",
}

#: How many constrained geometries each scan holds — its frame count. They are
#: deliberately unequal so that a split's frame count is not its unit count
#: times a constant, which is the one arrangement that cannot tell the two
#: numbers apart. Train is ``2 + 3 + 2 = 7`` frames over 3 units.
TORSION_CONSTRAINTS: Mapping[str, int] = {
    "scan-a": 2,
    "scan-b": 2,
    "scan-c": 3,
    "scan-d": 2,
    "scan-e": 1,
    "scan-f": 2,
}

#: ``uuid, identity, split`` rows of the torsion half of the derivation. A scan
#: uuid is a *scan* identity and shares no key space with the MBIS uuids, which
#: is why it is a separate table.
TORSION_SPLIT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("scan-a", HSSH_IDENTITY, "train"),
    ("scan-b", HOOH_IDENTITY, "val"),
    ("scan-c", HSSH_IDENTITY, "train"),
    ("scan-d", HSSH_IDENTITY, "train"),
    ("scan-e", HSOH_IDENTITY, "test"),
    ("scan-f", HOOH_IDENTITY, "val"),
)

#: What ``_SplitTable.counts()`` folds out of :data:`TORSION_SPLIT_ROWS`.
TORSION_SPLIT_COUNTS: Mapping[str, int] = {"train": 3, "val": 2, "test": 1}

#: The train scans in the order a sequential walk of the shards visits them.
TORSION_TRAIN_KEYS: tuple[str, ...] = ("scan-a", "scan-c", "scan-d")

SPLIT_COORDINATE = "dataset:molcrafts/class1-universal-splits@1"
SPLIT_SEED = 20260814
SPLIT_RATIOS = "8:1:1 train:val:test, molecule level"
SPLIT_GENERATOR = "scripts/build_class1_splits.py"

#: What the generator is called once it ships **inside** the wheel
#: (``src/molhub/scripts/build_class1_splits.py``) rather than beside it, and
#: the command a reader can actually type.
#:
#: :data:`SPLIT_GENERATOR` above deliberately keeps the *legacy* spelling: every
#: derivation already on disk records it in its own ``metadata.json``, and a
#: refusal that could only name the module because the metadata already did
#: would be pinning the fixture rather than the message. So the fixture writes
#: the old name and the refusals are required to state the new command anyway.
GENERATOR_MODULE = "molhub.scripts.build_class1_splits"
SPLIT_TABLE_COMMAND = f"python -m {GENERATOR_MODULE}"

#: The three THEMol index files that generator reads, by source name. A split
#: table cannot be rebuilt without all three, which is what makes the rebuild
#: expensive and what a "run the generator" message has to say out loud.
SPLIT_TABLE_INPUTS: tuple[str, ...] = ("hessian", "mbis", "torsion-scan")

#: The literal filenames from ``scripts/build_class1_splits.py``'s ``out_name``
#: block, mirrored (not imported) exactly as ``molhub.conveyor.splits`` does.
#: The torsion one carries no ``_uuid_`` — that irregularity is the producer's,
#: and restating it here is what keeps a wrong guess visible.
UUID_FILENAME = "mbis_uuid_splits.csv.gz"
TORSION_UUID_FILENAME = "torsion_scan_splits.csv.gz"
IDENTITY_FILENAME = "identity_splits.csv.gz"

#: Where the derivation lives under a molhub home, per the spec's D6.
SPLIT_SUBPATH = ("derived", "molcrafts", "class1-universal-splits", "1")

# ---------------------------------------------------------------------------
# The registry manifest. Sizes are declared metadata, not the fixture files'
# real sizes: nothing in the loader path verifies bytes, and three distinctive
# numbers make a wrong `download_size` sum visible instead of plausible.
# ---------------------------------------------------------------------------

INDEX_SIZE = 101
SHARD_0_SIZE = 1000
SHARD_1_SIZE = 10000

#: Every declared byte of the artifact — what a full download costs.
DOWNLOAD_SIZE = INDEX_SIZE + SHARD_0_SIZE + SHARD_1_SIZE

#: Copied verbatim from ``THEMolMBIS.manifest`` so a test that asserts on
#: ``DatasetInfo.description`` / ``.license`` / ``.citation`` pins the *content*
#: and stays silent about which of the two records the loader reads it from.
DESCRIPTION = "THEMol MBIS atomic electrostatic supervision."
LICENSE = "CC-BY-NC-4.0"
CITATION = "10.48550/arXiv.2605.14973"


def manifest_yaml(
    *,
    namespace: str = "themol",
    name: str = "mbis",
    version: str = "1",
    index_size: int = INDEX_SIZE,
) -> str:
    """A valid manifest for one version of the fixture dataset.

    Args:
        namespace: Coordinate namespace segment.
        name: Coordinate name segment.
        version: Coordinate version label.
        index_size: Declared byte size of the ``index`` role. The default is the
            three-digit :data:`INDEX_SIZE` every existing fixture sums; a caller
            that needs a *humanized* byte count to be observable — ``303 B``
            renders the same either way — passes something above a kibibyte.

    Returns:
        YAML in the shape ``scripts/generate_themol_manifests.py`` emits: one
        hot ``index`` role and two ``shard-*`` roles, in that order.
    """
    return (
        "schema_version: 1\n"
        "kind: dataset\n"
        f"namespace: {namespace}\n"
        f"name: {name}\n"
        f'version: "{version}"\n'
        "\n"
        "title: THEMol MBIS atomic electrostatics\n"
        f'description: "{DESCRIPTION}"\n'
        f"license: {LICENSE}\n"
        f"doi: {CITATION}\n"
        "\n"
        "artifacts:\n"
        "  - role: index\n"
        "    filename: mbis_dataset.csv\n"
        "    format: csv\n"
        f"    size: {index_size}\n"
        "    locators:\n"
        "      - fake://mbis-index\n"
        "  - role: shard-000\n"
        "    filename: mbis_0.h5\n"
        "    format: hdf5\n"
        f"    size: {SHARD_0_SIZE}\n"
        "    locators:\n"
        "      - fake://mbis-0\n"
        "  - role: shard-001\n"
        "    filename: mbis_1.h5\n"
        "    format: hdf5\n"
        f"    size: {SHARD_1_SIZE}\n"
        "    locators:\n"
        "      - fake://mbis-1\n"
    )


def build_registry(
    root: Path,
    *,
    versions: Sequence[str] = ("1",),
    namespace: str = "themol",
    name: str = "mbis",
    index_size: int = INDEX_SIZE,
) -> Registry:
    """Write one manifest per version under *root* and load them.

    The real :class:`~molhub.registry.Registry` over a directory of YAML is
    cheap, so the loader tests resolve against the type they will meet in
    production rather than against a stand-in with the same three methods.

    Args:
        root: Registry directory to create.
        versions: Version labels to declare for the artifact.
        namespace: Coordinate namespace segment.
        name: Coordinate name segment.
        index_size: Declared byte size of the ``index`` role; see
            :func:`manifest_yaml`.

    Returns:
        The loaded registry.
    """
    for version in versions:
        path = root / "dataset" / namespace / name / f"{version}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            manifest_yaml(namespace=namespace, name=name, version=version, index_size=index_size),
            encoding="utf-8",
        )
    return Registry.load(root)


# ---------------------------------------------------------------------------
# The shards.
# ---------------------------------------------------------------------------


def species_of(key: str) -> Species:
    """The species record *key* holds; water for a key nobody assigned one to."""
    return SPECIES[SPECIES_BY_KEY.get(key, "water")]


#: The two inverse Slater widths a fixture shell carries, in ``angstrom^-1``:
#: a core shell is tight and a valence shell is loose, which is the only thing
#: about them the loader path can observe. Real values land at ~24-67 and ~3-8
#: (probe recorded in ``tests/test_dataset/test_themol.py``).
CORE_WIDTH = 32.0
VALENCE_WIDTH = 5.0


def mbis_shell_rows(numbers: Sequence[int], charges: Sequence[float]) -> np.ndarray:
    """The ``(S, 3)`` MBIS Slater shell table of one fixture record.

    ``parameters`` is **not** per atom — it is one row per Slater *shell*
    (``src/molhub/dataset/themol.py``, ``_read_mbis``): column 0 addresses an
    atom, column 1 is that shell's population in electrons and column 2 its
    inverse Slater width. Hydrogen carries one shell and a heavier atom two
    (core, then valence), so ``S != N`` here exactly as in the real shards —
    water's three atoms make four rows.

    Populations divide each atom's ``Z - q``, so the fixture satisfies the sum
    rule the real data does (``sum(population) == Z.sum() - charge.sum()``)
    rather than carrying numbers that are merely the right shape.

    Args:
        numbers: Atomic numbers, in atom-map order.
        charges: The per-atom MBIS charge this record declares, same order.

    Returns:
        ``(S, 3)`` float64 rows, one atom's shells consecutive.
    """
    rows: list[tuple[float, float, float]] = []
    for index, (number, charge) in enumerate(zip(numbers, charges, strict=True)):
        electrons = float(number) - float(charge)
        if number == 1:
            rows.append((float(index), electrons, VALENCE_WIDTH))
            continue
        rows.append((float(index), 2.0, CORE_WIDTH))
        rows.append((float(index), electrons - 2.0, VALENCE_WIDTH))
    return np.asarray(rows, dtype=np.float64)


def write_shard(path: Path, keys: Sequence[str]) -> Path:
    """Write a THEMol MBIS shard holding one record per key in *keys*.

    The group layout mirrors ``tests/test_dataset/test_themol.py``'s builder —
    inline rather than imported, so the loader fixtures cannot be broken by an
    edit made for a THEMol reader test. Which molecule each key is comes from
    :func:`species_of`; the per-atom MBIS arrays are sized from it, so a shard
    of mixed species is as readable as a shard of one.

    Args:
        path: File to write.
        keys: Group keys, in the order they should be created.

    Returns:
        *path*, for chaining into a fake hub's role table.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    string = h5py.string_dtype("utf-8")
    with h5py.File(path, "w") as handle:
        for key in keys:
            species = species_of(key)
            n_atoms = len(species.numbers)
            group = handle.create_group(key)
            group.create_dataset("mapped_nonisomeric_smiles", data=species.smiles, dtype=string)
            group.create_dataset("mapped_isomeric_smiles", data=species.smiles, dtype=string)
            group.create_dataset(
                "atomic_numbers", data=np.asarray(species.numbers, dtype=np.int32)[:, None]
            )
            group.create_dataset("coords", data=species.coords)
            charges = [0.4 if number == 1 else -0.8 for number in species.numbers]
            info = group.create_group("mbis_info")
            info.create_dataset("atomic_volumes", data=np.ones((n_atoms, 1)))
            info.create_dataset("atomic_charge", data=np.asarray([[value] for value in charges]))
            info.create_dataset("atomic_dipole", data=np.ones((n_atoms, 3)))
            info.create_dataset("atomic_quadrupole", data=np.ones((n_atoms, 3, 3)))
            group.create_dataset("parameters", data=mbis_shell_rows(species.numbers, charges))
    return path


def torsion_species_of(key: str) -> Species:
    """The species scan *key* is; HSSH for a key nobody assigned one to."""
    return TORSION_SPECIES[TORSION_SPECIES_BY_KEY.get(key, "hssh")]


def write_torsion_shard(path: Path, keys: Sequence[str]) -> Path:
    """Write a THEMol torsion-scan shard holding one scan per key in *keys*.

    The group layout mirrors ``tests/test_dataset/test_themol.py``'s torsion
    builder — ``torsion_atom_indices`` beside the mapped SMILES, one
    ``constraint N`` subgroup per scanned geometry — inline rather than
    imported, for the reason :func:`write_shard` states. How many constraints
    each scan holds comes from :data:`TORSION_CONSTRAINTS`, so the fixture's
    frame counts are stated in one place.

    Args:
        path: File to write.
        keys: Group keys, in the order they should be created.

    Returns:
        *path*, for chaining into a fake hub's role table.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    string = h5py.string_dtype("utf-8")
    with h5py.File(path, "w") as handle:
        for key in keys:
            species = torsion_species_of(key)
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


# ---------------------------------------------------------------------------
# The split derivation.
# ---------------------------------------------------------------------------


def consistent_identity_rows() -> list[tuple[str, str]]:
    """The molecule-level assignment both uuid tables were folded from.

    One row per identity, in first-appearance order. HOOH appears in both
    fixture datasets and is ``val`` in each, so folding cannot produce two rows
    for one molecule — which is the property a molecule-level derivation has and
    a per-record one does not.

    Returns:
        ``(identity, split)`` rows, five of them.
    """
    folded = {identity: split for _, identity, split in (*SPLIT_ROWS, *TORSION_SPLIT_ROWS)}
    return list(folded.items())


def _write_rows(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write one gzipped CSV exactly as ``build_class1_splits.py`` writes it."""
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(header))
        for row in rows:
            writer.writerow(list(row))


def write_split_derivation(
    root: Path,
    *,
    identity_rows: Sequence[tuple[str, str]] | None = None,
) -> Path:
    """Write a miniature ``class1-universal-splits/1/`` directory at *root*.

    Both uuid-keyed tables are written — one per fixture dataset — beside the
    single molecule-level table they were folded from, which is the shape the
    real derivation has: one directory, one seed, one answer per molecule,
    however many subsets that molecule appears in.

    The ``output_sha256`` block is computed here, exactly as the producing
    script computes it, which is what makes the loaded table verifiable rather
    than merely present.

    Args:
        root: Directory to write the tables and ``metadata.json`` into.
        identity_rows: ``identity, split`` rows for the molecule-level table.
            ``None`` folds them out of :data:`SPLIT_ROWS` and
            :data:`TORSION_SPLIT_ROWS`, which is the consistent derivation. Pass
            a shorter list to build a derivation that assigns a *record* a split
            but not its *molecule* — the one state that makes a routing refusal
            reachable.

    Returns:
        *root*.
    """
    root.mkdir(parents=True, exist_ok=True)
    _write_rows(root / UUID_FILENAME, ("uuid", "identity", "split"), SPLIT_ROWS)
    _write_rows(root / TORSION_UUID_FILENAME, ("uuid", "identity", "split"), TORSION_SPLIT_ROWS)
    _write_rows(
        root / IDENTITY_FILENAME,
        ("identity", "split"),
        identity_rows if identity_rows is not None else consistent_identity_rows(),
    )
    metadata = {
        "coordinate": SPLIT_COORDINATE,
        "seed": SPLIT_SEED,
        "ratios": SPLIT_RATIOS,
        "generator": SPLIT_GENERATOR,
        "output_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (UUID_FILENAME, TORSION_UUID_FILENAME, IDENTITY_FILENAME)
        },
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return root


def corrupt_split_table(root: Path, *, filename: str = UUID_FILENAME) -> Path:
    """Change one table's bytes *after* its ``metadata.json`` recorded them.

    The one state that is neither "the derivation is not here" nor "the
    derivation is fine": the directory, the record and the file all exist, and
    the file is no longer what the record says it is. Distinguishing that from
    an absent derivation is the whole of the first ruling — one is a rebuild the
    reader has never run, the other is bytes that changed under them.

    Args:
        root: The derivation directory, already written.
        filename: Which of its tables to disturb.

    Returns:
        The path whose bytes no longer verify.
    """
    path = root / filename
    path.write_bytes(path.read_bytes() + b"\n")
    return path


# ---------------------------------------------------------------------------
# The verified manifest: the same artifact, with the bytes it really has.
#
# `manifest_yaml` above declares three distinctive fake sizes and no digest,
# because the map-style path verifies nothing. A streaming walk goes through
# `ShardTransfer`, which re-checks size *and* digest against the manifest and
# deletes anything that disagrees, so its fixture manifest has to state the
# truth about the files on disk. Two manifests rather than one switchable one:
# a test reading `DOWNLOAD_SIZE` and a test watching a byte budget want
# different, incompatible things from the same field.
# ---------------------------------------------------------------------------


def verified_manifest_yaml(
    files: Mapping[str, Path],
    *,
    namespace: str = "themol",
    name: str = "mbis",
    version: str = "1",
    title: str = "THEMol MBIS atomic electrostatics",
    description: str = DESCRIPTION,
) -> str:
    """A manifest declaring the real size and sha256 of every file in *files*.

    Filenames and locators are derived from *name*, so a manifest for the
    torsion fixture does not declare files called ``mbis_0.h5``: a refusal
    message quotes the filename it could not fit, and a fixture that lied about
    it would make that message unreadable.

    Args:
        files: Shard role to the file whose bytes that role serves, in the
            order the manifest should declare them — which is the order a
            streaming walk visits them in.
        namespace: Coordinate namespace segment.
        name: Coordinate name segment.
        version: Coordinate version label.
        title: Human title the manifest declares.
        description: Prose the manifest declares.

    Returns:
        YAML in the shape :func:`manifest_yaml` emits, with one hot ``index``
        role and one ``shard-*`` role per entry of *files*.
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
        f"namespace: {namespace}\n"
        f"name: {name}\n"
        f'version: "{version}"\n'
        "\n"
        f"title: {title}\n"
        f'description: "{description}"\n'
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
    root: Path,
    files: Mapping[str, Path],
    *,
    namespace: str = "themol",
    name: str = "mbis",
    version: str = "1",
    title: str = "THEMol MBIS atomic electrostatics",
    description: str = DESCRIPTION,
) -> Registry:
    """Write and load a registry whose declared bytes are *files*' real bytes.

    Args:
        root: Registry directory to create.
        files: Shard role to the file it serves.
        namespace: Coordinate namespace segment.
        name: Coordinate name segment.
        version: Coordinate version label.
        title: Human title the manifest declares.
        description: Prose the manifest declares.

    Returns:
        The loaded registry.
    """
    path = root / "dataset" / namespace / name / f"{version}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        verified_manifest_yaml(
            files,
            namespace=namespace,
            name=name,
            version=version,
            title=title,
            description=description,
        ),
        encoding="utf-8",
    )
    return Registry.load(root)


# ---------------------------------------------------------------------------
# The fake hub: an ArtifactHub over files already on disk, counting every call.
# ---------------------------------------------------------------------------


class FakeHub:
    """An :class:`~molhub.dataset.hub.ArtifactHub` that hands back local paths.

    It counts calls because the whole of ac-004 is a claim about a number of
    fetches, and it can be :meth:`seal`\\ ed because "reuses the index without
    reopening the shard" is only provable by making the reopen loud.

    Args:
        files: Role to the local path this hub serves for it.
    """

    def __init__(self, files: Mapping[str, Path]) -> None:
        self._files = dict(files)
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.sealed = False

    @property
    def fetch_count(self) -> int:
        """How many times :meth:`fetch` has been called."""
        return len(self.calls)

    @property
    def roles_fetched(self) -> tuple[str, ...]:
        """Every role asked for, in call order, repeats included."""
        return tuple(role for _, roles in self.calls for role in roles)

    def seal(self) -> None:
        """Make any further fetch an error instead of a silent re-read."""
        self.sealed = True

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Return the local path of every requested role."""
        if self.sealed:
            raise AssertionError(
                f"a sealed hub was asked for {coordinate} roles={roles!r}; the caller "
                "reopened bytes it was supposed to have memoized."
            )
        requested = tuple(roles) if roles is not None else tuple(self._files)
        missing = [role for role in requested if role not in self._files]
        if missing:
            raise KeyError(
                f"{coordinate} has no role {missing}; this hub serves {sorted(self._files)}"
            )
        self.calls.append((coordinate, requested))
        return {role: self._files[role] for role in requested}


class NoticeWatchingHub(FakeHub):
    """A :class:`FakeHub` that records what was on stderr *before* each fetch.

    "The notice is printed before the bytes move" is a claim about order, and
    order is only observable from something that watched. ``capsys`` can be
    drained mid-test — :meth:`pytest.CaptureFixture.readouterr` returns what has
    been captured so far and resets — so draining it at the top of every fetch
    turns the ordering claim into a list of strings a test can assert on:
    ``notices[0]`` is everything stderr held before the first byte was asked
    for, ``notices[1]`` everything between the first fetch and the second.

    Args:
        files: Role to the local path this hub serves for it.
        capture: What drains stderr and returns it — ``lambda:
            capsys.readouterr().err`` at the call site, so this class needs no
            pytest fixture of its own.
    """

    def __init__(self, files: Mapping[str, Path], *, capture: Callable[[], str]) -> None:
        super().__init__(files)
        self._capture = capture
        self.notices: list[str] = []

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Record stderr as it stands, then serve the requested roles."""
        self.notices.append(self._capture())
        return super().fetch(coordinate, roles=roles)


#: The conveyor's vocabulary, which ``hf-facade-04``'s ac-003 keeps off every
#: value the loader returns and every message it raises. ``"ledger"`` and
#: ``"conveyor"`` are in it because the canonical ledger path is
#: ``<home>/conveyor/ledger.jsonl``: a message quoting it would leak both the
#: file and the concept, which is complaint (4) verbatim.
CONVEYOR_VOCABULARY: tuple[str, ...] = (
    "BlockId",
    "BlockState",
    "LedgerRecord",
    "LeaseRecord",
    "shard-",
    "ledger",
    "lease",
    "conveyor",
)


def leaks(text: str) -> list[str]:
    """Every piece of :data:`CONVEYOR_VOCABULARY` *text* carries.

    Returns a list rather than a bool so a failing assertion names the word that
    leaked instead of saying ``False != True``.
    """
    return [word for word in CONVEYOR_VOCABULARY if word in text]


#: Where the conveyor keeps its bookkeeping under a molhub home. Spelled out
#: here by hand, exactly as ``tests/test_cli.py::TestCacheStatus`` spells the
#: tier directories out: this is the layout contract, and a fixture that asked
#: production where to write could not tell a wrong path from a right one. It is
#: also what ``molhub.conveyor.default_ledger_path`` must agree with.
LEDGER_SEGMENTS: tuple[str, ...] = ("conveyor", "ledger.jsonl")


@dataclass(frozen=True)
class Fetch:
    """What the world looked like at the instant one fetch was asked for.

    A streaming walk's whole claim is about *order* — the previous shard's bytes
    are gone, and its release is recorded, before the next shard is asked for —
    and order is only observable from something that watched. This is that
    something, captured by :class:`LandingHub` before it lands a single byte.

    Attributes:
        roles: The roles this fetch asked for, in call order.
        resident: Shard roles whose cache file existed when the fetch arrived.
        ledger: The conveyor ledger file's text at that instant, or ``""`` when
            no ledger had been written yet.
    """

    roles: tuple[str, ...]
    resident: tuple[str, ...]
    ledger: str


class LandingHub(FakeHub):
    """A :class:`FakeHub` that **lands** its bytes at the real cache path.

    :class:`FakeHub` hands back the path it was constructed with, which is all a
    map-style reader needs. A streaming walk deletes what it fetched, so a hub
    that handed back the pristine fixture file would have the walk delete the
    fixture — and the second visit would find nothing to serve. This one copies
    the pristine bytes to ``$MOLHUB_HOME/files/<coordinate>/<role>``, which is
    where :class:`~molhub.sources.fetcher.Fetcher` would have put them, and
    returns that path. Deleting it is then exactly the rolling-tier delete, and
    a re-fetch genuinely re-lands the bytes.

    Args:
        files: Role to the pristine file whose bytes that role serves. These are
            never handed out and never deleted.
        home: The molhub home the cache sits under.
        coordinate: The artifact whose roles these are.
    """

    def __init__(
        self,
        files: Mapping[str, Path],
        *,
        home: Path,
        coordinate: str = COORDINATE,
    ) -> None:
        super().__init__(files)
        self._store = BlobStore(home)
        self._coordinate = Coordinate.parse(coordinate)
        self._ledger = Path(home).joinpath(*LEDGER_SEGMENTS)
        self.fetches: list[Fetch] = []

    def cache_path(self, role: str) -> Path:
        """Where role *role*'s bytes live once fetched — the Fetcher's own key."""
        return self._store.path_for(f"{self._coordinate.cache_path()}/{role}")

    def resident(self) -> tuple[str, ...]:
        """The shard roles whose cache file exists right now, in manifest order."""
        return tuple(role for role in self._files if self.cache_path(role).is_file())

    def resident_bytes(self) -> int:
        """How many bytes of fetched-and-not-yet-deleted shard files are on disk."""
        return sum(self.cache_path(role).stat().st_size for role in self.resident())

    def ledger_text(self) -> str:
        """The conveyor ledger file's text, or ``""`` when nothing wrote one."""
        try:
            return self._ledger.read_text(encoding="utf-8")
        except OSError:
            return ""

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Land every requested role at its cache path and return the cache paths."""
        served = super().fetch(coordinate, roles=roles)
        self.fetches.append(
            Fetch(roles=tuple(served), resident=self.resident(), ledger=self.ledger_text())
        )
        landed: dict[str, Path] = {}
        for role, source in served.items():
            target = self.cache_path(role)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            landed[role] = target
        return landed


# ---------------------------------------------------------------------------
# The two whole-view fixture datasets: a miniature QM9 and a miniature
# polymer-tg.
#
# Both are registry datasets whose class the builder can construct from a
# coordinate and a hub alone, and neither declares a split — so the HF idiom is
# that their entire content is served as `train`. Counting that content means
# *reading* it, which is why they are built here in miniature: the real QM9 is
# 86 MB of bz2 holding 130 831 molecules, and a test that counted those would be
# measuring tarfile rather than the loader.
#
# The declared sizes are the artifacts' *manifest* metadata, not the fixture
# files' real sizes (as in `manifest_yaml` above), and they are chosen so that
# their humanized rendering is not their raw one: `ByteSize(3_145_728)` is
# `3.0 MiB`, which is what makes "the notice states both" observable.
# ---------------------------------------------------------------------------

QM9_COORDINATE = "dataset:molcrafts/qm9@v2"

#: The two published QM9 roles, as `molhub.dataset.qm9` fetches them, and the
#: byte size each manifest declares. Distinct, so a total that dropped one is
#: visible rather than plausible.
QM9_MAIN_SIZE = 3_000_000
QM9_EXCLUDE_SIZE = 145_728

#: Every declared byte of the miniature QM9 — 3.0 MiB exactly, so the humanized
#: form in the download notice is a literal a test can pin.
QM9_DOWNLOAD_SIZE = QM9_MAIN_SIZE + QM9_EXCLUDE_SIZE

#: The molecule indices the fixture tarball holds, and the ones its
#: uncharacterized list excludes. Five in, two out, three left: three differs
#: from both, so a count that read the wrong list cannot pass.
QM9_INDICES: tuple[int, ...] = (1, 2, 3, 4, 5)
QM9_EXCLUDED: tuple[int, ...] = (2, 4)
QM9_RECORD_COUNT = len(QM9_INDICES) - len(QM9_EXCLUDED)

#: The fifteen scalar targets a QM9 record carries, as the real manifest
#: declares them.
QM9_TARGETS: tuple[str, ...] = (
    "A",
    "B",
    "C",
    "mu",
    "alpha",
    "homo",
    "lumo",
    "gap",
    "r2",
    "zpve",
    "U0",
    "U",
    "H",
    "G",
    "Cv",
)

POLYMER_TG_COORDINATE = "dataset:molcrafts/polymer-tg@1"

#: The one published polymer-tg role's declared size — 2.0 MiB exactly, for the
#: reason :data:`QM9_DOWNLOAD_SIZE` states.
POLYMER_TG_SIZE = 2_097_152

#: The target column the polymer-tg manifest declares, spelled as upstream
#: spells it (the dot and the parenthesised unit are part of the column name).
POLYMER_TG_TARGET = "labels.Exp_Tg(K)"

#: The rows of the miniature CSV: one PSMILES and one glass-transition
#: temperature each. Floats, so the parsed value cannot be confused with a row
#: index, and four of them because four is not three.
POLYMER_TG_ROWS: tuple[tuple[str, float], ...] = (
    ("[*]CC[*]", 300.5),
    ("[*]CC(C)[*]", 373.5),
    ("[*]CC(c1ccccc1)[*]", 373.0),
    ("[*]CC(Cl)[*]", 354.5),
)
POLYMER_TG_RECORD_COUNT = len(POLYMER_TG_ROWS)


def qm9_xyz_record(index: int, *, u0: float) -> str:
    """One structurally faithful raw QM9 record: one carbon, 15 scalars.

    The second line carries ``tag``, ``index`` and the fifteen properties in the
    order ``molhub.dataset.qm9._PROPERTY_NAMES`` reads them; the coordinate line
    carries the trailing Mulliken charge the parser ignores.

    Args:
        index: The molecule index, which also lands in the member filename.
        u0: The ``U0`` value, distinct per record so a reader that returned the
            wrong molecule is visible.

    Returns:
        The record's extended-XYZ text.
    """
    return (
        "1\n"
        f"gdb {index} 1.0 2.0 3.0 0 1.0 -0.1 0.1 0.2 1.0 0.01 "
        f"{u0} -1.0 -1.0 -1.0 1.0\n"
        "C 0.0 0.0 0.0 0.0\n"
    )


def write_qm9_payload(
    root: Path,
    *,
    indices: Sequence[int] = QM9_INDICES,
    excluded: Sequence[int] = QM9_EXCLUDED,
) -> dict[str, Path]:
    """Write a miniature QM9 payload under *root*, by published role.

    Member names follow the real ``dsgdb9nsd_%06d.xyz`` convention because
    ``molhub.dataset.qm9`` recovers the molecule index by slicing the filename,
    and the exclusion list keeps the nine header lines and the trailer line its
    reader skips. Mirrored from ``tests/test_dataset/test_qm9.py``'s builder
    rather than imported, exactly as :func:`write_shard` mirrors the THEMol
    one: a fixture for the loader must not break because a reader test was
    edited.

    Args:
        root: Directory to write the two files into.
        indices: Molecule indices the tarball holds.
        excluded: Molecule indices the uncharacterized list names.

    Returns:
        ``{"main": tarball, "exclude": list}`` — the two roles a hub serves.
    """
    root.mkdir(parents=True, exist_ok=True)
    tarball = root / "dsgdb9nsd.xyz.tar.bz2"
    with tarfile.open(tarball, "w:bz2") as archive:
        for index in indices:
            payload = qm9_xyz_record(index, u0=float(-index)).encode("utf-8")
            info = tarfile.TarInfo(name=f"dsgdb9nsd_{index:06d}.xyz")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    header = "\n".join(f"header {line}" for line in range(9))
    body = "\n".join(f"{index} 0.0" for index in excluded)
    exclude = root / "uncharacterized.txt"
    exclude.write_text(f"{header}\n{body}\ntrailer\n", encoding="utf-8")
    return {"main": tarball, "exclude": exclude}


def qm9_manifest_yaml() -> str:
    """A manifest for ``dataset:molcrafts/qm9@v2``, in the shape ``v2.yaml`` has.

    Two roles — the tarball and the uncharacterized list — with the declared
    sizes this module states and no digest, because nothing on the loader path
    verifies bytes.
    """
    targets = ", ".join(QM9_TARGETS)
    return (
        "schema_version: 1\n"
        "kind: dataset\n"
        "namespace: molcrafts\n"
        "name: qm9\n"
        'version: "v2"\n'
        "\n"
        "title: QM9 miniature\n"
        'description: "Five-molecule stand-in for the GDB-9 subset."\n'
        "license: CC0-1.0\n"
        "doi: 10.1038/sdata.2014.22\n"
        "\n"
        "artifacts:\n"
        "  - role: main\n"
        "    filename: dsgdb9nsd.xyz.tar.bz2\n"
        f"    size: {QM9_MAIN_SIZE}\n"
        "    locators:\n"
        "      - fake://qm9-main\n"
        "  - role: exclude\n"
        "    filename: uncharacterized.txt\n"
        f"    size: {QM9_EXCLUDE_SIZE}\n"
        "    locators:\n"
        "      - fake://qm9-exclude\n"
        "\n"
        "targets:\n"
        f"  graph_level: [{targets}]\n"
        "  atom_level: []\n"
    )


def write_polymer_tg_csv(path: Path, rows: Sequence[tuple[str, float]] = POLYMER_TG_ROWS) -> Path:
    """Write the miniature LAMALAB polymer-Tg CSV at *path*.

    Args:
        path: File to write.
        rows: ``(psmiles, Tg)`` pairs, one per data row.

    Returns:
        *path*, for chaining into a fake hub's role table.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("PSMILES", POLYMER_TG_TARGET))
        writer.writerows(rows)
    return path


def polymer_tg_manifest_yaml() -> str:
    """A manifest for ``dataset:molcrafts/polymer-tg@1``, one ``main`` CSV role."""
    return (
        "schema_version: 1\n"
        "kind: dataset\n"
        "namespace: molcrafts\n"
        "name: polymer-tg\n"
        'version: "1"\n'
        "\n"
        "title: LAMALAB polymer glass-transition miniature\n"
        'description: "Four-row stand-in for the LAMALAB curated Tg table."\n'
        "license: CC-BY-4.0\n"
        "doi: 10.5281/zenodo.14980914\n"
        "\n"
        "artifacts:\n"
        "  - role: main\n"
        "    filename: LAMALAB_CURATED_Tg_structured.csv\n"
        f"    size: {POLYMER_TG_SIZE}\n"
        "    locators:\n"
        "      - fake://polymer-tg-main\n"
        "\n"
        "targets:\n"
        f'  graph_level: ["{POLYMER_TG_TARGET}"]\n'
        "  atom_level: []\n"
    )


def build_manifest_registry(root: Path, *, path: Sequence[str], text: str) -> Registry:
    """Write one hand-written manifest under *root* and load the registry.

    The sibling of :func:`build_registry` for the datasets whose manifests are
    not THEMol-shaped: those two roles are ``main`` / ``exclude``, not
    ``index`` / ``shard-*``, and a shard-shaped stand-in would let a whole-view
    declaration pass while fetching roles no real manifest publishes.

    Args:
        root: Registry directory to create.
        path: Path segments under *root*, e.g.
            ``("dataset", "molcrafts", "qm9", "v2.yaml")``.
        text: The manifest YAML.

    Returns:
        The loaded registry.
    """
    manifest = root.joinpath(*path)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(text, encoding="utf-8")
    return Registry.load(root)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def shard_paths(tmp_path: Path) -> dict[str, Path]:
    """The two fixture shards on disk, keyed by manifest role."""
    root = tmp_path / "shards"
    return {role: write_shard(root / f"{role}.h5", keys) for role, keys in SHARD_KEYS.items()}


@pytest.fixture
def hub(shard_paths: dict[str, Path]) -> FakeHub:
    """A fake hub serving the fixture shards, with a fetch counter."""
    return FakeHub(shard_paths)


@pytest.fixture
def splits_root(tmp_path: Path) -> Path:
    """A provenance-consistent miniature split derivation, ready to load."""
    return write_split_derivation(tmp_path.joinpath("home", *SPLIT_SUBPATH))


@pytest.fixture
def layout(tmp_path: Path) -> DerivedLayout:
    """The derived layout a shard index memoizes itself under."""
    return DerivedLayout(tmp_path / "home", subdir="derived")


@pytest.fixture
def molhub_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``$MOLHUB_HOME`` pointed at ``tmp_path``, split derivation already in it."""
    home = tmp_path / "home"
    write_split_derivation(home.joinpath(*SPLIT_SUBPATH))
    monkeypatch.setenv("MOLHUB_HOME", str(home))
    return home


@pytest.fixture
def bare_molhub_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``$MOLHUB_HOME`` pointed at a home with **no** split derivation in it.

    The sibling of :func:`molhub_home`, and the state every reader is in before
    they have ever built the table: the home exists, the cache under it may even
    be warm, and ``derived/`` is simply not there. Absent is not corrupt, so it
    gets its own fixture rather than a flag on the other one.
    """
    home = tmp_path / "bare-home"
    home.mkdir()
    monkeypatch.setenv("MOLHUB_HOME", str(home))
    return home


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    """A registry declaring exactly ``dataset:themol/mbis@1``."""
    return build_registry(tmp_path / "registry")


@pytest.fixture
def pristine_shards(tmp_path: Path) -> dict[str, Path]:
    """The two fixture shards, kept outside the cache and never handed out.

    Distinct from :func:`shard_paths`: these are the bytes a streaming hub
    *serves*, so they survive the walk deleting what it fetched.
    """
    root = tmp_path / "pristine"
    return {role: write_shard(root / f"{role}.h5", keys) for role, keys in SHARD_KEYS.items()}


@pytest.fixture
def verified_registry(tmp_path: Path, pristine_shards: dict[str, Path]) -> Registry:
    """A registry whose declared shard sizes and digests are the real ones."""
    return build_verified_registry(tmp_path / "verified-registry", pristine_shards)


@pytest.fixture
def landing_hub(pristine_shards: dict[str, Path], molhub_home: Path) -> LandingHub:
    """A hub that lands the fixture shards at their cache paths, and watches."""
    return LandingHub(pristine_shards, home=molhub_home)


@pytest.fixture
def ledger_path(molhub_home: Path) -> Path:
    """The one conveyor ledger under this home — the path, not the file."""
    return molhub_home.joinpath(*LEDGER_SEGMENTS)


@pytest.fixture
def pristine_torsion_shards(tmp_path: Path) -> dict[str, Path]:
    """The two torsion-scan shards, kept outside the cache and never handed out."""
    root = tmp_path / "pristine-torsion"
    return {
        role: write_torsion_shard(root / f"{role}.h5", keys)
        for role, keys in TORSION_SHARD_KEYS.items()
    }


@pytest.fixture
def verified_torsion_registry(tmp_path: Path, pristine_torsion_shards: dict[str, Path]) -> Registry:
    """A registry declaring ``dataset:themol/torsion-scan@1`` with real bytes."""
    return build_verified_registry(
        tmp_path / "verified-torsion-registry",
        pristine_torsion_shards,
        name="torsion-scan",
        title="THEMol constrained torsion profiles",
        description="THEMol complete constrained torsion profiles.",
    )


@pytest.fixture
def torsion_hub(pristine_torsion_shards: dict[str, Path], molhub_home: Path) -> LandingHub:
    """A hub that lands the torsion-scan shards at their cache paths, and watches."""
    return LandingHub(pristine_torsion_shards, home=molhub_home, coordinate=TORSION_COORDINATE)


@pytest.fixture
def qm9_hub(tmp_path: Path) -> FakeHub:
    """A counting hub serving the miniature QM9 tarball and exclusion list."""
    return FakeHub(write_qm9_payload(tmp_path / "qm9-payload"))


@pytest.fixture
def qm9_registry(tmp_path: Path) -> Registry:
    """A registry declaring exactly ``dataset:molcrafts/qm9@v2``."""
    return build_manifest_registry(
        tmp_path / "qm9-registry",
        path=("dataset", "molcrafts", "qm9", "v2.yaml"),
        text=qm9_manifest_yaml(),
    )


@pytest.fixture
def polymer_tg_hub(tmp_path: Path) -> FakeHub:
    """A counting hub serving the miniature polymer-Tg CSV as role ``main``."""
    path = write_polymer_tg_csv(tmp_path / "polymer-tg-payload" / "polymer_tg.csv")
    return FakeHub({"main": path})


@pytest.fixture
def polymer_tg_registry(tmp_path: Path) -> Registry:
    """A registry declaring exactly ``dataset:molcrafts/polymer-tg@1``."""
    return build_manifest_registry(
        tmp_path / "polymer-tg-registry",
        path=("dataset", "molcrafts", "polymer-tg", "1.yaml"),
        text=polymer_tg_manifest_yaml(),
    )
