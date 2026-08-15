"""Build the Class-I universal identity + split manifests from THEMol indexes.

Implements `.claude/specs/universal-class-i-01-dataset-composition.md` §18/§19
(ac-005): normalize molecular graphs -> global molecular identity ->
molecule-level train/validation/test split -> only then configuration
sampling. All structures belonging to one molecular identity stay in one
split; a torsion scan inherits its molecule's split (scan rows key the same
identity), so grouped targets can never straddle splits.

Global identity
    THEMol's ``mapped_isomeric_smiles`` strings are byte-identical for the
    same molecule across the hessian / torsion-scan / mbis subsets (verified
    2026-08-14: 2,371,035 of the 2,436,985 torsion molecules match hessian
    strings exactly), so identity = blake2b-128 of that string. The
    torsion-scan ``uuid`` column is a *scan* identity, not a molecule
    identity (zero uuid overlap with hessian/mbis) — do not key splits on it.

Outputs (in the artifact directory ``DerivedLayout`` files this coordinate
under, ``$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1/``):
    identity_splits.csv.gz        identity,split          one row per molecule
    hessian_uuid_splits.csv.gz    uuid,identity,split     per hessian molecule
    mbis_uuid_splits.csv.gz       uuid,identity,split     per mbis molecule
    torsion_scan_splits.csv.gz    uuid,identity,split     per torsion scan
    provenance record             seed, ratios, counts, input sha256s, written
                                  by ``DerivedLayout.write_metadata``

The directory shape and the provenance record are not this module's rules:
:class:`molhub.conveyor.tier.DerivedLayout` owns both, and the conveyor's blocks
tier uses the same object. The bytes are unchanged — same ``indent=2``, same key
order, same trailing newline — so re-running against the same inputs and seed
still reproduces the shipped artifact exactly.

**Where the inputs come from.** The three THEMol index files are asked for
through :class:`~molhub.molhub.Molhub`, not read off a hand-built cache path: an
index already fetched costs nothing, and one that is missing is *retrievable*
rather than fatal. Retrievable is not free — the real indexes run to gigabytes —
so the default is to say what the download would cost and stop. ``--fetch`` is
the reader saying yes, and until they do, nothing is fetched and nothing is
written.

Deterministic and re-runnable: same inputs + seed -> byte-identical outputs.

Usage:
    MOLHUB_HOME=/path/to/molhub-home \
    python -m molhub.scripts.build_class1_splits [--fetch] [--seed 20260814]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from molhub.conveyor import DerivedLayout, THEMolUnitEncoder
from molhub.coordinate import Coordinate
from molhub.dataset.hub import ArtifactHub
from molhub.molhub import Molhub
from molhub.registry import Registry
from molhub.sources import BlobStore, Fetcher

__all__ = ["RATIOS", "SOURCES", "ThemolIndexes", "MoleculeSplits", "main"]

#: How this generator is spelled everywhere a reader is told to run it: the
#: ``prog`` of its own parser, the ``generator`` field of the ``metadata.json``
#: it writes, and — mirrored as a literal, for the reason
#: ``molhub.conveyor.splits`` mirrors its filename table — the command the
#: loader's refusals name. Written out rather than read off ``__spec__``, which
#: says ``__main__`` under some launchers and is exactly the spelling a reader
#: cannot type.
MODULE = "molhub.scripts.build_class1_splits"

#: train : val : test, molecule level (the espaloma precedent).
RATIOS = (8, 1, 1)

#: The three THEMol subsets one molecular identity may appear in, and the
#: coordinate publishing each. All three are read: a split table folded from two
#: of them would assign the third's molecules by accident or not at all.
SOURCES: Mapping[str, str] = MappingProxyType(
    {
        "hessian": "dataset:themol/hessian@1",
        "torsion-scan": "dataset:themol/torsion-scan@1",
        "mbis": "dataset:themol/mbis@1",
    }
)

SMILES_COL = "mapped_isomeric_smiles"

# The role every THEMol artifact publishes its index CSV under.
_INDEX_ROLE = "index"

# The output filenames, irregular exactly as `molhub.conveyor.splits` mirrors
# them: the torsion one carries no `_uuid_`.
_IDENTITY_FILENAME = "identity_splits.csv.gz"
_SOURCE_FILENAMES: Mapping[str, str] = MappingProxyType(
    {
        "hessian": "hessian_uuid_splits.csv.gz",
        "mbis": "mbis_uuid_splits.csv.gz",
        "torsion-scan": "torsion_scan_splits.csv.gz",
    }
)

# Every published table, in the order `output_sha256` records them. Pinned as a
# literal so the recorded key order — and therefore the metadata bytes — does not
# follow whatever order the sources happen to iterate in.
_OUTPUT_FILENAMES: tuple[str, ...] = (
    "identity_splits.csv.gz",
    "hessian_uuid_splits.csv.gz",
    "mbis_uuid_splits.csv.gz",
    "torsion_scan_splits.csv.gz",
)

# Where the derivation is filed, and under which coordinate.
_DERIVED_SUBDIR = "derived"
_COORDINATE = "dataset:molcrafts/class1-universal-splits@1"
_NAMESPACE = "molcrafts"
_NAME = "class1-universal-splits"
_VERSION = "1"

_DEFAULT_SEED = 20260814


class ThemolIndexes:
    """The three THEMol index CSVs this derivation is folded from.

    Every index is asked for through the hub, so a cached one is read without a
    transfer and an absent one is a *retrievable* file rather than a dead path.
    What that retrieval would cost is answered before it is spent:
    :meth:`absent` says which indexes are not on this machine and
    :meth:`download_size` says what fetching them declares.

    Args:
        registry: Where each index's declared size is read from.
        hub: Where index bytes come from; a cache hit costs nothing.
        home: The molhub home whose cache is probed. Probing is a read — it
            creates no directory and fetches nothing.
    """

    def __init__(self, *, registry: Registry, hub: ArtifactHub, home: str | Path) -> None:
        self._registry = registry
        self._hub = hub
        self._blobs = BlobStore(home)

    def absent(self) -> tuple[str, ...]:
        """The sources whose index is not in this home's cache.

        Returns:
            Source names in declaration order. Empty means every input is
            already local, which is what makes re-running this generator free.
        """
        return tuple(
            name
            for name, coordinate in SOURCES.items()
            if not self._blobs.has(self._key(coordinate))
        )

    def download_size(self, sources: Sequence[str]) -> int:
        """How many bytes fetching *sources*' indexes would pull.

        Args:
            sources: Source names, usually the result of :meth:`absent`.

        Returns:
            The sum of the sizes their manifests declare. Declared rather than
            measured: the files are not here, which is the whole question.
        """
        return sum(self._declared_size(name) for name in sources)

    def paths(self) -> dict[str, Path]:
        """Every index file, resolved through the hub.

        Returns:
            Source name to the local path holding that index's bytes.

        Raises:
            AllLocatorsFailed: If an absent index cannot be retrieved.
        """
        return {
            name: self._hub.fetch(coordinate, roles=[_INDEX_ROLE])[_INDEX_ROLE]
            for name, coordinate in SOURCES.items()
        }

    def rows(self, paths: Mapping[str, Path]) -> dict[str, list[tuple[str, str]]]:
        """The ``(uuid, identity)`` rows of each index, in file order.

        Args:
            paths: Source name to its index file, from :meth:`paths`.

        Returns:
            Source name to its rows. File order is preserved, so the per-source
            tables written from it are byte-reproducible.
        """
        return {name: self._read(path) for name, path in paths.items()}

    @staticmethod
    def digest(path: Path) -> str:
        """The sha256 of one input file, recorded so a run states what it read."""
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 22), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def identity_of(smiles: str) -> str:
        """Molecular identity — the one implementation, owned by the encoder.

        The conveyor's prepare stage *routes* by the same number, and split
        production drifting apart from split routing would mis-route molecules
        with nothing able to detect it, so the rule lives in
        :meth:`~molhub.conveyor.encoder.THEMolUnitEncoder.identity` and this
        module calls it. The digest is unchanged from the derivation already
        shipped under ``derived/molcrafts/class1-universal-splits/1``.
        """
        return THEMolUnitEncoder.identity(smiles)

    def _read(self, path: Path) -> list[tuple[str, str]]:
        """Read one index CSV into ``(uuid, identity)`` rows, in file order."""
        rows: list[tuple[str, str]] = []
        with open(path, newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            uuid_col = header.index("uuid")
            smiles_col = header.index(SMILES_COL)
            for row in reader:
                rows.append((row[uuid_col], self.identity_of(row[smiles_col])))
        return rows

    def _declared_size(self, name: str) -> int:
        """The byte size *name*'s manifest declares for its index role."""
        manifest = self._registry.get(SOURCES[name])
        return manifest.artifact(_INDEX_ROLE).size or 0

    @staticmethod
    def _key(coordinate: str) -> str:
        """The cache key an index occupies — coordinate plus role, as everywhere."""
        return f"{Coordinate.parse(coordinate).cache_path()}/{_INDEX_ROLE}"


class MoleculeSplits:
    """One split per molecular identity — the level every table is folded from.

    The assignment is a seeded shuffle of the sorted identity universe, so the
    same inputs and the same seed reproduce it exactly. Every conformer, scan and
    subset row of one molecule therefore lands in one split, which is the
    property that keeps grouped targets from straddling splits.

    Args:
        identities: Every identity the inputs mention; duplicates are folded, so
            a molecule appearing in three subsets is still one draw.
        seed: What fixes the shuffle, and what a run records so the assignment is
            re-derivable.
        ratios: train : val : test. Applied with floor division on the train and
            val shares, the remainder going to test.
    """

    def __init__(
        self,
        identities: Iterable[str],
        *,
        seed: int,
        ratios: tuple[int, int, int] = RATIOS,
    ) -> None:
        universe = sorted(set(identities))
        random.Random(seed).shuffle(universe)
        total = sum(ratios)
        size = len(universe)
        n_train = size * ratios[0] // total
        n_val = size * ratios[1] // total
        self._assignment: dict[str, str] = {
            identity: "train" if index < n_train else "val" if index < n_train + n_val else "test"
            for index, identity in enumerate(universe)
        }
        self._counts: Mapping[str, int] = MappingProxyType(
            {"train": n_train, "val": n_val, "test": size - n_train - n_val}
        )

    @property
    def size(self) -> int:
        """How many distinct molecules were assigned."""
        return len(self._assignment)

    def counts(self) -> Mapping[str, int]:
        """How many molecules each split drew."""
        return self._counts

    def split_of(self, identity: str) -> str:
        """The split *identity* was assigned.

        Raises:
            KeyError: If *identity* was not part of the universe. There is no
                default: a fabricated split leaks between train and test with
                nothing able to detect it.
        """
        return self._assignment[identity]

    def rows(self) -> list[tuple[str, str]]:
        """``(identity, split)`` rows, sorted by identity — the published order."""
        return [(identity, self._assignment[identity]) for identity in sorted(self._assignment)]


def main(
    argv: Sequence[str] | None = None,
    *,
    registry: Registry | None = None,
    hub: ArtifactHub | None = None,
) -> int:
    """Write the Class-I split derivation under this molhub home.

    Args:
        argv: Command-line arguments; ``None`` reads :data:`sys.argv`.
        registry: Where manifests come from; ``None`` loads the configured or
            bundled registry.
        hub: Where index bytes come from; ``None`` constructs a
            :class:`~molhub.molhub.Molhub` whose cache is the selected home, so
            what this module probes and what the hub serves are one directory.

    Returns:
        ``0`` when the derivation was written, ``1`` when an input index is
        missing and ``--fetch`` was not given — in which case nothing was
        fetched and nothing was created.
    """
    parser = argparse.ArgumentParser(
        prog=f"python -m {MODULE}",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument(
        "--molhub-home",
        type=Path,
        default=Path(os.environ.get("MOLHUB_HOME", Path.home() / ".cache" / "molhub")),
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Authorise downloading any THEMol index this machine does not have.",
    )
    args = parser.parse_args(argv)

    home = args.molhub_home
    registry = registry if registry is not None else Registry.load()
    hub = hub if hub is not None else Molhub(registry, fetcher=Fetcher(blobs=BlobStore(home)))
    indexes = ThemolIndexes(registry=registry, hub=hub, home=home)

    absent = indexes.absent()
    if absent and not args.fetch:
        print(
            f"{len(absent)} of the {len(SOURCES)} THEMol indexes this derivation is folded "
            f"from are not under {home}: {', '.join(absent)}. Fetching them would download "
            f"{indexes.download_size(absent)} B, which is not a side effect a script should "
            "have. Re-run with --fetch to authorise it. Nothing was fetched and nothing "
            "was written.",
            file=sys.stderr,
        )
        return 1

    print("resolving input indexes ...", flush=True)
    paths = indexes.paths()

    print("hashing input indexes ...", flush=True)
    input_digests = {name: ThemolIndexes.digest(path) for name, path in paths.items()}

    print("reading indexes ...", flush=True)
    per_source = indexes.rows(paths)

    splits = MoleculeSplits(
        (identity for rows in per_source.values() for _, identity in rows), seed=args.seed
    )

    layout = DerivedLayout(home, subdir=_DERIVED_SUBDIR)
    out_dir = layout.artifact_dir(_NAMESPACE, _NAME, _VERSION)

    with gzip.open(out_dir / _IDENTITY_FILENAME, "wt", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["identity", "split"])
        for identity, split in splits.rows():
            writer.writerow([identity, split])

    counts: dict[str, dict[str, int]] = {}
    for name, rows in per_source.items():
        tally = {"train": 0, "val": 0, "test": 0}
        with gzip.open(out_dir / _SOURCE_FILENAMES[name], "wt", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["uuid", "identity", "split"])
            for uuid, identity in rows:
                split = splits.split_of(identity)
                tally[split] += 1
                writer.writerow([uuid, identity, split])
        counts[name] = tally

    metadata: dict[str, object] = {
        "coordinate": _COORDINATE,
        "spec": "molhub:.claude/specs/universal-class-i-01-dataset-composition.md (ac-005)",
        "identity": f"blake2b-128 of {SMILES_COL} (byte-identical across THEMol subsets)",
        "seed": args.seed,
        "ratios": "8:1:1 train:val:test, molecule level",
        "n_identities": splits.size,
        "identity_counts": dict(splits.counts()),
        "per_source_row_counts": counts,
        "source_coordinates": dict(SOURCES),
        "input_index_sha256": input_digests,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generator": MODULE,
        "output_sha256": {
            filename: ThemolIndexes.digest(out_dir / filename) for filename in _OUTPUT_FILENAMES
        },
    }
    layout.write_metadata(out_dir, metadata)

    print(json.dumps({k: v for k, v in metadata.items() if k != "output_sha256"}, indent=2))
    print(f"outputs -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
