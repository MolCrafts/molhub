"""Shared fixtures for the loader tests — one synthetic THEMol dataset, no network.

What ``tests/test_conveyor/conftest.py`` is to the conveyor, this is to the
loader: every byte a loader test reads is written into ``tmp_path`` here, so no
test depends on ``$MOLHUB_HOME`` as the developer happens to have it, on the
bundled registry snapshot, or on the 150 GB of real THEMol shards.

**Nothing here imports ``molhub.loader`` or ``molhub.conveyor.splits``.** The
first does not exist yet and the second is mid-rename (``SplitTable`` ->
``_SplitTable``); a conftest that imported either would turn every test in this
package — including ``test_layering.py``, which is answerable today — into one
collection error instead of failures with names on them.

The fixture dataset is ``dataset:themol/mbis@1`` in miniature: two shards of
three water records each, and the miniature ``class1-universal-splits@1``
derivation that assigns them. The rows are chosen so that

* the three splits have three *different* counts (train 3, val 2, test 1), so a
  test cannot pass by reading the wrong split's number, and
* one shard holds two train rows while the other holds one, which is the only
  arrangement that can tell "walked on to the next shard" apart from "re-read
  the shard it already had".
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import h5py
import numpy as np
import pytest

from molhub.conveyor.tier import DerivedLayout
from molhub.registry import Registry

# ---------------------------------------------------------------------------
# The fixture dataset: two shards of dataset:themol/mbis@1.
# ---------------------------------------------------------------------------

COORDINATE = "dataset:themol/mbis@1"

#: Atom-map order H:1, O:2, H:3 — deliberately unlike SMILES parse order, the
#: same water record ``tests/test_dataset/test_themol.py`` reads.
WATER = "[O:2]([H:1])[H:3]"
WATER_NUMBERS: tuple[int, ...] = (1, 8, 1)
WATER_COORDS = np.asarray([[-0.7, 0.0, 0.0], [0.0, 0.0, 0.0], [0.7, 0.0, 0.0]], dtype=np.float64)

#: Which HDF5 group keys each shard holds, in the order h5py lists them.
SHARD_KEYS: Mapping[str, tuple[str, ...]] = {
    "shard-000": ("mbis-a", "mbis-b", "mbis-c"),
    "shard-001": ("mbis-d", "mbis-e", "mbis-f"),
}

#: ``uuid, identity, split`` rows of the miniature split derivation. Train rows
#: land in both shards, two of them in the first.
SPLIT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mbis-a", "identity-1", "train"),
    ("mbis-b", "identity-2", "val"),
    ("mbis-c", "identity-3", "train"),
    ("mbis-d", "identity-4", "train"),
    ("mbis-e", "identity-5", "test"),
    ("mbis-f", "identity-6", "val"),
)

#: What ``_SplitTable.counts()`` folds out of :data:`SPLIT_ROWS`.
SPLIT_COUNTS: Mapping[str, int] = {"train": 3, "val": 2, "test": 1}

#: The train rows in the order a sequential walk of the shards visits them.
TRAIN_KEYS: tuple[str, ...] = ("mbis-a", "mbis-c", "mbis-d")

SPLIT_COORDINATE = "dataset:molcrafts/class1-universal-splits@1"
SPLIT_SEED = 20260814
SPLIT_RATIOS = "8:1:1 train:val:test, molecule level"
SPLIT_GENERATOR = "scripts/build_class1_splits.py"

#: The literal filenames from ``scripts/build_class1_splits.py``'s ``out_name``
#: block, mirrored (not imported) exactly as ``molhub.conveyor.splits`` does.
UUID_FILENAME = "mbis_uuid_splits.csv.gz"
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


def manifest_yaml(*, namespace: str = "themol", name: str = "mbis", version: str = "1") -> str:
    """A valid manifest for one version of the fixture dataset.

    Args:
        namespace: Coordinate namespace segment.
        name: Coordinate name segment.
        version: Coordinate version label.

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
        f"    size: {INDEX_SIZE}\n"
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

    Returns:
        The loaded registry.
    """
    for version in versions:
        path = root / "dataset" / namespace / name / f"{version}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            manifest_yaml(namespace=namespace, name=name, version=version), encoding="utf-8"
        )
    return Registry.load(root)


# ---------------------------------------------------------------------------
# The shards.
# ---------------------------------------------------------------------------


def write_shard(path: Path, keys: Sequence[str]) -> Path:
    """Write a THEMol MBIS shard holding one water record per key in *keys*.

    The group layout mirrors ``tests/test_dataset/test_themol.py``'s builder —
    inline rather than imported, so the loader fixtures cannot be broken by an
    edit made for a THEMol reader test.

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
            group = handle.create_group(key)
            group.create_dataset("mapped_nonisomeric_smiles", data=WATER, dtype=string)
            group.create_dataset("mapped_isomeric_smiles", data=WATER, dtype=string)
            group.create_dataset(
                "atomic_numbers", data=np.asarray(WATER_NUMBERS, dtype=np.int32)[:, None]
            )
            group.create_dataset("coords", data=WATER_COORDS)
            info = group.create_group("mbis_info")
            info.create_dataset("atomic_volumes", data=np.ones((3, 1)))
            info.create_dataset("atomic_charge", data=np.asarray([[0.4], [-0.8], [0.4]]))
            info.create_dataset("atomic_dipole", data=np.ones((3, 3)))
            info.create_dataset("atomic_quadrupole", data=np.ones((3, 3, 3)))
            group.create_dataset(
                "parameters", data=np.asarray([[0.0, 1.0], [2.0, 3.0], [4.0, 5.0]])
            )
    return path


# ---------------------------------------------------------------------------
# The split derivation.
# ---------------------------------------------------------------------------


def _write_rows(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write one gzipped CSV exactly as ``build_class1_splits.py`` writes it."""
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(header))
        for row in rows:
            writer.writerow(list(row))


def write_split_derivation(root: Path) -> Path:
    """Write a miniature ``class1-universal-splits/1/`` directory at *root*.

    The ``output_sha256`` block is computed here, exactly as the producing
    script computes it, which is what makes the loaded table verifiable rather
    than merely present.

    Args:
        root: Directory to write the tables and ``metadata.json`` into.

    Returns:
        *root*.
    """
    root.mkdir(parents=True, exist_ok=True)
    _write_rows(root / UUID_FILENAME, ("uuid", "identity", "split"), SPLIT_ROWS)
    _write_rows(
        root / IDENTITY_FILENAME,
        ("identity", "split"),
        ((identity, split) for _, identity, split in SPLIT_ROWS),
    )
    metadata = {
        "coordinate": SPLIT_COORDINATE,
        "seed": SPLIT_SEED,
        "ratios": SPLIT_RATIOS,
        "generator": SPLIT_GENERATOR,
        "output_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (UUID_FILENAME, IDENTITY_FILENAME)
        },
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return root


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
def registry(tmp_path: Path) -> Registry:
    """A registry declaring exactly ``dataset:themol/mbis@1``."""
    return build_registry(tmp_path / "registry")
