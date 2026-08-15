#!/usr/bin/env python
r"""Regression: describe a dataset by content, then read one split of it.

``hf-facade-03-builder-info`` gave molhub the HuggingFace spelling —
``load_dataset_builder("themol/mbis").info`` and
``load_dataset("themol/mbis", split="train")`` — and this script drives it
through the public surface only, offline, over a synthetic two-shard artifact
written into a temporary directory:

* **ac-001.** ``"themol/mbis"`` resolves to the pinned coordinate
  ``dataset:themol/mbis@1``; a registry whose versions do not order refuses
  rather than picking one.
* **ac-002.** ``info`` describes content — description, license, citation, 15
  features with their level and units (the 14 per-atom columns plus the
  ``mbis_shells`` block), split counts, record type, download size — and the
  substring ``shard-`` appears in no rendered field.
* **ac-003.** ``split`` is a required keyword; omitting it is a ``TypeError``,
  not a container of splits.
* **ac-004 / ac-005.** ``len(ds)`` is the split table's count with zero fetches
  recorded by the injected hub; reading a row fetches exactly the shard that
  owns it, and a second row of the same shard fetches nothing new.

Determinism: no network, no clock-dependent assertion, no torch and no molnex
(asserted below, right after the imports). ``$MOLHUB_HOME`` is *set* to the
temporary directory for the duration — the loader files its shard-key memo and
reads its split derivation under that root — and restored afterwards, so the
developer's own cache is neither read nor written.

Provenance of the goldens (hard-coded literals; nothing is recomputed here):

* ``WATER_MOLECULE_ID`` is ``uuid5(UUID(int=0), "[O:2]([H:1])[H:3]").hex``, the
  same literal ``regressions/hf-facade-02-frame-records.py`` pins for the same
  SMILES (CPython stdlib; 2026-08-15).
* The split counts ``train 3 / val 2 / test 1`` and the train key order
  ``mbis-a, mbis-c, mbis-d`` are hand-derived from the six-row split table this
  script writes: three different counts, and train rows in both shards.
* ``DOWNLOAD_SIZE = 11101`` is the sum of the three declared artifact sizes in
  the manifest below (101 + 1000 + 10000). The sizes are declared metadata, not
  the fixture files' real sizes: nothing on this path verifies bytes, and three
  distinctive numbers make a wrong sum visible instead of plausible.
* The 15 feature names, levels and units are ``THEMolMBIS``'s own declarations —
  the 14 ``atom``-level columns ``atomic_charge``, ``atomic_volume``, three
  ``dipole_<axis>`` and nine ``quadrupole_<axis><axis>``, with ``THEMOL_UNITS``
  values, plus the ``block``-level ``mbis_shells`` — written out here as
  literals so a schema edit shows up as a decision.
* The MBIS ``parameters`` **shape and column meanings** — ``(S, 3)`` of
  ``(atom index, shell population in e, inverse Slater width in angstrom^-1)``,
  with a variable shell count per atom — come from a one-off offline probe of
  1000 groups of the real published THEMol mbis ``shard-000`` (430906 groups),
  read with h5py; date 2026-08-15. The identity ``sum(population) == Z.sum() -
  charge.sum()`` held exactly on every probed group. Nothing here reads that
  shard: ``WATER_SHELL_ROWS`` below is synthetic and hand-picked to satisfy the
  same identity, and the probe is quoted, not repeated.

tool: python
command: python regressions/hf-facade-03-builder-info.py
date: 2026-08-15
"""

from __future__ import annotations

import csv
import dataclasses
import gzip
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import molhub  # noqa: E402
from molhub.loader import AmbiguousRevision  # noqa: E402
from molhub.registry import Registry  # noqa: E402

assert "torch" not in sys.modules, "importing molhub pulled torch into sys.modules"
assert "molix" not in sys.modules, "importing molhub pulled molix into sys.modules"

import h5py  # noqa: E402
import numpy as np  # noqa: E402

# ---------------------------------------------------------------------------
# The fixture artifact: two shards of dataset:themol/mbis@1, three records each.
# ---------------------------------------------------------------------------

COORDINATE = "dataset:themol/mbis@1"
DESCRIPTION = "THEMol MBIS atomic electrostatic supervision."
LICENSE = "CC-BY-NC-4.0"
CITATION = "10.48550/arXiv.2605.14973"

WATER = "[O:2]([H:1])[H:3]"
WATER_NUMBERS = (1, 8, 1)
WATER_COORDS = np.asarray([[-0.5, 0.0, 0.0], [0.0, 0.0, 0.0], [0.5, 0.0, 0.0]], dtype=np.float64)
WATER_MOLECULE_ID = "7164234ff61f524e828d817795c1e285"
WATER_CHARGES = np.asarray([[0.5], [-1.0], [0.5]], dtype=np.float64)

#: The fixture record's MBIS Slater shells, as the source's ``(S, 3)`` rows
#: ``(atom index, shell population in e, inverse Slater width in angstrom^-1)``.
#: Four rows for three atoms: by atom-map order (H:1, O:2, H:3) atom 1 is the
#: oxygen and it carries a core and a valence shell while each hydrogen carries
#: one — the shape a per-atom ``(N, arity)`` array cannot represent, which is
#: why this fixture would load under the old reader and must not now. The
#: populations are hand-picked so the probed identity holds here too:
#: ``sum(population) == Z.sum() - charge.sum()`` == 10 - 0.0 == 10.0; the
#: per-shell split is synthetic. Same four rows as
#: ``regressions/hf-facade-02-frame-records.py``, so the two scripts' fixture
#: water is one molecule.
WATER_SHELL_ROWS = ((0.0, 0.5, 3.25), (1.0, 2.0, 32.0), (1.0, 6.5, 6.75), (2.0, 1.0, 3.5))

SHARD_KEYS: Mapping[str, tuple[str, ...]] = {
    "shard-000": ("mbis-a", "mbis-b", "mbis-c"),
    "shard-001": ("mbis-d", "mbis-e", "mbis-f"),
}

SPLIT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mbis-a", "identity-1", "train"),
    ("mbis-b", "identity-2", "val"),
    ("mbis-c", "identity-3", "train"),
    ("mbis-d", "identity-4", "train"),
    ("mbis-e", "identity-5", "test"),
    ("mbis-f", "identity-6", "val"),
)
SPLIT_COUNTS: Mapping[str, int] = {"test": 1, "train": 3, "val": 2}
TRAIN_KEYS = ("mbis-a", "mbis-c", "mbis-d")

SPLIT_COORDINATE = "dataset:molcrafts/class1-universal-splits@1"
SPLIT_SUBPATH = ("derived", "molcrafts", "class1-universal-splits", "1")
UUID_FILENAME = "mbis_uuid_splits.csv.gz"
IDENTITY_FILENAME = "identity_splits.csv.gz"

INDEX_SIZE = 101
SHARD_0_SIZE = 1000
SHARD_1_SIZE = 10000
DOWNLOAD_SIZE = 11101

#: Everything ``THEMolMBIS`` declares, with the level and the unit it declares
#: for it, in the order ``info.features`` reports (name order): its fourteen
#: ``atoms`` columns, plus the ``mbis_shells`` block the Slater shells land in.
#: The block renders at level ``block`` with an **empty** unit, and that blank
#: is a declaration too: its two float columns disagree on their unit
#: (``population`` in ``e``, ``inverse_width`` in ``angstrom^-1``), so no single
#: string would be right for both and the dataset states none rather than
#: picking one.
FEATURES: tuple[tuple[str, str, str], ...] = (
    ("atomic_charge", "atom", "e"),
    ("atomic_volume", "atom", "angstrom^3"),
    ("dipole_x", "atom", "e*angstrom"),
    ("dipole_y", "atom", "e*angstrom"),
    ("dipole_z", "atom", "e*angstrom"),
    ("mbis_shells", "block", ""),
    ("quadrupole_xx", "atom", "e*angstrom^2"),
    ("quadrupole_xy", "atom", "e*angstrom^2"),
    ("quadrupole_xz", "atom", "e*angstrom^2"),
    ("quadrupole_yx", "atom", "e*angstrom^2"),
    ("quadrupole_yy", "atom", "e*angstrom^2"),
    ("quadrupole_yz", "atom", "e*angstrom^2"),
    ("quadrupole_zx", "atom", "e*angstrom^2"),
    ("quadrupole_zy", "atom", "e*angstrom^2"),
    ("quadrupole_zz", "atom", "e*angstrom^2"),
)


def manifest_yaml(*, version: str = "1") -> str:
    """One version of the fixture manifest: a hot index plus two shard roles."""
    return (
        "schema_version: 1\n"
        "kind: dataset\n"
        "namespace: themol\n"
        "name: mbis\n"
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


def write_registry(root: Path, versions: Sequence[str] = ("1",)) -> Registry:
    """Write one manifest per version under *root* and load them."""
    for version in versions:
        path = root / "dataset" / "themol" / "mbis" / f"{version}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest_yaml(version=version), encoding="utf-8")
    return Registry.load(root)


def write_shard(path: Path, keys: Sequence[str]) -> Path:
    """Write one MBIS shard holding one water record per key in *keys*."""
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
            info.create_dataset("atomic_charge", data=WATER_CHARGES)
            info.create_dataset("atomic_dipole", data=np.ones((3, 3)))
            info.create_dataset("atomic_quadrupole", data=np.ones((3, 3, 3)))
            group.create_dataset("parameters", data=np.asarray(WATER_SHELL_ROWS, dtype=np.float64))
    return path


def _write_rows(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
    """Write one gzipped CSV exactly as ``scripts/build_class1_splits.py`` does."""
    with gzip.open(path, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(header))
        for row in rows:
            writer.writerow(list(row))


def write_split_derivation(root: Path) -> Path:
    """Write a miniature, provenance-consistent ``class1-universal-splits/1/``."""
    root.mkdir(parents=True, exist_ok=True)
    _write_rows(root / UUID_FILENAME, ("uuid", "identity", "split"), SPLIT_ROWS)
    _write_rows(
        root / IDENTITY_FILENAME,
        ("identity", "split"),
        ((identity, split) for _, identity, split in SPLIT_ROWS),
    )
    metadata = {
        "coordinate": SPLIT_COORDINATE,
        "seed": 20260814,
        "ratios": "8:1:1 train:val:test, molecule level",
        "generator": "scripts/build_class1_splits.py",
        "output_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in (UUID_FILENAME, IDENTITY_FILENAME)
        },
    }
    (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return root


class CountingHub:
    """An ``ArtifactHub`` over local files that records every call.

    ac-004 is a claim about a *number of fetches*, so the substitute hub counts
    them rather than merely serving paths.
    """

    def __init__(self, files: Mapping[str, Path]) -> None:
        self._files = dict(files)
        self.roles_fetched: list[str] = []

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Return the local path of every requested role."""
        requested = tuple(roles) if roles is not None else tuple(self._files)
        missing = [role for role in requested if role not in self._files]
        if missing:
            raise KeyError(f"{coordinate} has no role {missing}")
        self.roles_fetched.extend(requested)
        return {role: self._files[role] for role in requested}


# ---------------------------------------------------------------------------
# Checks.
# ---------------------------------------------------------------------------


def check_info_describes_content(registry: Registry, hub: CountingHub) -> None:
    """ac-001 + ac-002: one pinned coordinate, and content with no role in it."""
    builder = molhub.load_dataset_builder("themol/mbis", registry=registry, hub=hub)
    info = builder.info

    assert info.coordinate.canonical == COORDINATE, info.coordinate
    assert info.description == DESCRIPTION, info.description
    assert info.license == LICENSE, info.license
    assert info.citation == CITATION, info.citation
    assert info.record_type == "Frame", info.record_type
    assert info.download_size == DOWNLOAD_SIZE, info.download_size

    rendered = tuple((f.name, f.level, f.units) for f in info.features)
    assert rendered == FEATURES, rendered

    counted = {split.name: split.num_examples for split in info.splits}
    assert counted == dict(SPLIT_COUNTS), counted
    # Pinned before the `all(...)` below, which a zero-split info would satisfy
    # vacuously: three splits are reported, and each one names its derivation.
    assert len(info.splits) == 3, info.splits
    assert all(SPLIT_COORDINATE in split.provenance for split in info.splits), info.splits

    # ac-002, made mechanical: the manifest this was built from has three roles.
    fields = {field.name: str(getattr(info, field.name)) for field in dataclasses.fields(info)}
    offenders = sorted(name for name, value in fields.items() if "shard-" in value)
    assert offenders == [], offenders
    assert "shard-" not in repr(info)

    # Describing is free: not one shard byte was asked for.
    assert hub.roles_fetched == [], hub.roles_fetched


def check_split_is_a_required_keyword(registry: Registry, hub: CountingHub) -> None:
    """ac-003: no dict-of-splits, no default split — a missing argument."""
    try:
        molhub.load_dataset("themol/mbis")  # type: ignore[call-arg]
    except TypeError:
        pass
    else:  # pragma: no cover - the failure branch of a regression script
        raise AssertionError("load_dataset accepted a call with no split")

    try:
        molhub.load_dataset("themol/mbis", "train", registry=registry, hub=hub)  # type: ignore[misc]
    except TypeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("load_dataset accepted split as a positional argument")

    assert not hasattr(molhub.loader, "DatasetDict")


def check_rows_are_the_split_in_shard_order(registry: Registry, hub: CountingHub) -> None:
    """ac-004 + ac-005: length is free, rows fetch the shard that owns them."""
    train = molhub.load_dataset("themol/mbis", split="train", registry=registry, hub=hub)

    assert len(train) == SPLIT_COUNTS["train"] == 3, len(train)
    assert hub.roles_fetched == [], hub.roles_fetched

    first = train[0]
    assert first.meta["source_record_id"] == "mbis-a", first.meta["source_record_id"]
    assert first.meta["source_id"] == f"{COORDINATE}#role=shard-000", first.meta["source_id"]
    assert first.meta["molecule_id"] == WATER_MOLECULE_ID, first.meta["molecule_id"]
    assert first.meta["total_charge"] == 0, first.meta["total_charge"]
    assert list(first["atoms"]["number"]) == list(WATER_NUMBERS)
    assert list(first["atoms"]["atomic_charge"]) == [0.5, -1.0, 0.5]
    assert hub.roles_fetched == ["shard-000"], hub.roles_fetched

    # A second row of the same shard costs nothing new; a later one walks on.
    assert train[1].meta["source_record_id"] == "mbis-c"
    assert hub.roles_fetched == ["shard-000"], hub.roles_fetched
    assert train[2].meta["source_record_id"] == "mbis-d"
    assert hub.roles_fetched == ["shard-000", "shard-001"], hub.roles_fetched

    walked = tuple(train[i].meta["source_record_id"] for i in range(len(train)))
    assert walked == TRAIN_KEYS, walked

    other = molhub.load_dataset("themol/mbis", split="val", registry=registry, hub=hub)
    assert len(other) == SPLIT_COUNTS["val"] == 2, len(other)


def check_unorderable_versions_are_refused(root: Path, hub: CountingHub) -> None:
    """ac-001: a silently picked version is not a pinned one."""
    registry = write_registry(root, versions=("v2", "beta"))
    try:
        molhub.load_dataset_builder("themol/mbis", registry=registry, hub=hub).info
    except AmbiguousRevision as error:
        message = str(error)
        assert "v2" in message and "beta" in message, message
    else:  # pragma: no cover
        raise AssertionError("an unorderable version set resolved to something")

    pinned = molhub.load_dataset_builder("themol/mbis", revision="beta", registry=registry, hub=hub)
    assert pinned.info.coordinate.canonical == "dataset:themol/mbis@beta"


def main() -> None:
    """Build the fixture artifact in a temporary directory and check it."""
    with tempfile.TemporaryDirectory(prefix="molhub-hf-facade-03-") as workdir:
        root = Path(workdir)
        home = root / "home"
        write_split_derivation(home.joinpath(*SPLIT_SUBPATH))
        shards = {
            role: write_shard(root / "shards" / f"{role}.h5", keys)
            for role, keys in SHARD_KEYS.items()
        }
        registry = write_registry(root / "registry")

        previous = os.environ.get("MOLHUB_HOME")
        os.environ["MOLHUB_HOME"] = str(home)
        try:
            check_info_describes_content(registry, CountingHub(shards))
            check_split_is_a_required_keyword(registry, CountingHub(shards))
            check_rows_are_the_split_in_shard_order(registry, CountingHub(shards))
            check_unorderable_versions_are_refused(root / "versions", CountingHub(shards))
        finally:
            if previous is None:
                os.environ.pop("MOLHUB_HOME", None)
            else:
                os.environ["MOLHUB_HOME"] = previous

    print("hf-facade-03-builder-info: OK")


if __name__ == "__main__":
    main()
