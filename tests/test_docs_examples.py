"""Execute every Python fence in the documentation, or report its explicit skip.

Three directives, and what each promises the reader who copies the fence:

``<!-- test: exec -->``
    Runs verbatim against the environment the reader already has — the
    **bundled** registry and whatever ``$MOLHUB_HOME`` they happen to have.
    Nothing here exports ``$MOLHUB_REGISTRY`` for one of these: the
    ``Molhub().resolve("polymer-tg@1")`` fence is a claim about the registry
    that ships inside the wheel, and pointing it at a synthetic directory would
    make it pass by reading a file this repo wrote for it.

``<!-- test: fixture-home -->``
    Runs verbatim against a synthetic ``$MOLHUB_HOME`` **and**
    ``$MOLHUB_REGISTRY`` holding one miniature ``dataset:themol/mbis@1`` — two
    published files of three records, the split derivation that assigns them,
    and the shard bytes already in the cache so a fetch is a cache hit and no
    locator is ever resolved. A *fresh* home per fence, because a streaming
    walk consumes and deletes the file it read: one shared home would leave the
    fence after it reading a cache the fence before it emptied.

``<!-- test: skip <reason> -->``
    Not run. The reason is printed, so a fence nobody executes still says why.

**Why the fixture is a class in this module rather than a conftest fixture.**
It has exactly one caller — this harness — and ``tests/`` holds no
free-floating helper modules, so it stays where it is used until a second
caller exists. It is deliberately *not* imported from
``tests/test_loader/conftest.py`` either: those fixtures serve the loader's own
unit tests and are edited for them, and a docs harness silently retargeted by
an edit made for a different test is worse than fifty lines of literal here.
The literal shapes (the ``(S, 3)`` MBIS Slater-shell rows, the six records over
two files, the three-way split) mirror
``regressions/hf-facade-04-streaming-prepare.py``; nothing is imported from
``regressions/``, which is standalone-runnable by contract.

Every value the fences assert on is a *declaration* — ``Feature('atomic_charge',
'atom', 'e')`` comes from ``THEMolMBIS``'s own ``@dataset`` block,
``describe_download_size == 0`` from ``TableBackedSplits``, ``take(1).limit``
from ``BoundedStream`` — so the fixture supplies bytes and never an answer.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
FENCE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)
ANNOTATED = re.compile(r"<!--\s*test:\s*([^>]+?)\s*-->\s*```python\s*\n(.*?)```", re.DOTALL)

# ---------------------------------------------------------------------------
# The miniature dataset the `fixture-home` fences read. Literals, not lookups:
# the fixture states what it writes, and production is what interprets it.
# ---------------------------------------------------------------------------

#: The one artifact the fences name. The version matters: `THEMolMBIS.COORDINATE`
#: is `dataset:themol/mbis@1`, and the shipped collection declaration that says
#: which files are walkable names that exact string.
NAMESPACE = "themol"
NAME = "mbis"
VERSION = "1"

#: Where a fetched file lands under a molhub home — `<home>/files/<kind>/<ns>/
#: <name>@<version>/<role>`, spelled out by hand as the layout contract it is.
#: Seeding the cache at this path is what makes `Molhub().fetch` a cache hit.
CACHE_SUBPATH: tuple[str, ...] = ("files", "dataset", f"{NAMESPACE}/{NAME}@{VERSION}")

#: Where the split derivation lives under a molhub home, and the two tables of
#: it these fences need: the uuid-keyed one a split view filters by, and the
#: molecule-level one it was folded from.
SPLIT_SUBPATH: tuple[str, ...] = ("derived", "molcrafts", "class1-universal-splits", "1")
SPLIT_COORDINATE = "dataset:molcrafts/class1-universal-splits@1"
UUID_FILENAME = "mbis_uuid_splits.csv.gz"
IDENTITY_FILENAME = "identity_splits.csv.gz"
SPLIT_SEED = 20260814
SPLIT_RATIOS = "8:1:1 train:val:test, molecule level"
SPLIT_GENERATOR = "scripts/build_class1_splits.py"

DESCRIPTION = "THEMol MBIS atomic electrostatic supervision."
LICENSE = "CC-BY-NC-4.0"
CITATION = "10.48550/arXiv.2605.14973"
TITLE = "THEMol MBIS atomic electrostatics"

#: The declared size of the `index` role. It carries no digest and is never
#: fetched — only `shard-*` roles are walkable, and only they are seeded — so a
#: distinctive fake number is honest here and a real file would be theatre.
INDEX_SIZE = 101

#: Atom-mapped isomeric SMILES, atomic numbers in atom-map order and the
#: molecular identity (blake2b-128 of the SMILES) of each fixture molecule.
#: The identities are pinned literals mirrored from
#: `regressions/hf-facade-04-streaming-prepare.py`, never recomputed here.
WATER_IDENTITY = "810eef0a316c3ae716b15724bd6a8779"
HOOH_IDENTITY = "159fcddf7a882e2d79a52e4f129e2459"
HF_IDENTITY = "b0881071b1d54c8fb0d6817885e2a9ab"

SMILES: Mapping[str, str] = {
    "water": "[O:2]([H:1])[H:3]",
    "hooh": "[H:1][O:2][O:3][H:4]",
    "hf": "[H:1][F:2]",
}
NUMBERS: Mapping[str, tuple[int, ...]] = {
    "water": (1, 8, 1),
    "hooh": (1, 8, 8, 1),
    "hf": (1, 9),
}
IDENTITIES: Mapping[str, str] = {
    "water": WATER_IDENTITY,
    "hooh": HOOH_IDENTITY,
    "hf": HF_IDENTITY,
}

#: Each species' MBIS Slater shells as the source publishes them: `(S, 3)` rows
#: of `(atom index, shell population in e, inverse Slater width in
#: angstrom^-1)`, one row per *shell*, so `S > n_atoms`. Hand-derived from the
#: charges `_write_shard` assigns (0.4 for H, -0.8 otherwise) so every atom's
#: shells sum to its own population `Z_atom - q_atom`. Mirrored from
#: `regressions/hf-facade-04-streaming-prepare.py::MBIS_SHELL_ROWS`, whose
#: docstring records the offline probe of the real published shard that the
#: shape and the sum rule come from.
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

#: Which record keys each published file holds, in the order h5py lists them.
SHARD_KEYS: Mapping[str, tuple[str, ...]] = {
    "shard-000": ("mbis-a", "mbis-b", "mbis-c"),
    "shard-001": ("mbis-d", "mbis-e", "mbis-f"),
}

#: Which molecule each record is. A molecule never straddles two splits, which
#: is what a molecule-level derivation guarantees and what lets the uuid-keyed
#: and identity-keyed tables below agree.
SPECIES_BY_KEY: Mapping[str, str] = {
    "mbis-a": "water",
    "mbis-b": "hooh",
    "mbis-c": "water",
    "mbis-d": "water",
    "mbis-e": "hf",
    "mbis-f": "hooh",
}

#: `uuid, identity, split` rows of the miniature derivation: train 3, val 2,
#: test 1 — three different counts, and two of the train rows in the first
#: published file so `train[0]` and a `take(1)` walk both stop inside it. The
#: names are `train` / `val` / `test`, which is what makes the documented
#: `split="validation"` an `UnknownSplit` rather than a typo that happens to
#: work.
SPLIT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("mbis-a", WATER_IDENTITY, "train"),
    ("mbis-b", HOOH_IDENTITY, "val"),
    ("mbis-c", WATER_IDENTITY, "train"),
    ("mbis-d", WATER_IDENTITY, "train"),
    ("mbis-e", HF_IDENTITY, "test"),
    ("mbis-f", HOOH_IDENTITY, "val"),
)


class FixtureHome:
    """A synthetic ``$MOLHUB_HOME`` + ``$MOLHUB_REGISTRY``, built from nothing.

    Everything a ``fixture-home`` fence touches is written here: the two
    published files, the registry manifest declaring their **real** sizes and
    sha256 (a streaming walk re-verifies both and deletes what disagrees), the
    split derivation with its own provenance record, and the same shard bytes
    already sitting at their cache path so ``Molhub().fetch`` short-circuits
    before it ever looks at a locator.

    Args:
        root: Directory to build under; created, and owned entirely by this
            fixture.
    """

    def __init__(self, root: Path) -> None:
        self.home = root / "home"
        self.registry = root / "registry"
        self.cwd = root / "cwd"
        self.cwd.mkdir(parents=True)
        cached = {role: self._write_shard(role, keys) for role, keys in SHARD_KEYS.items()}
        self._write_manifest(cached)
        self._write_split_derivation()

    @property
    def env(self) -> dict[str, str]:
        """The two variables a fence is run with, pointing at this fixture."""
        return {"MOLHUB_HOME": str(self.home), "MOLHUB_REGISTRY": str(self.registry)}

    def cache_path(self, role: str) -> Path:
        """Where role *role*'s bytes live under this home — the fetcher's key."""
        return self.home.joinpath(*CACHE_SUBPATH, role)

    def _write_shard(self, role: str, keys: Sequence[str]) -> Path:
        """Write one published THEMol MBIS file straight into the cache.

        Args:
            role: The manifest role these bytes are published under.
            keys: Record keys, in the order the file should hold them.

        Returns:
            The cached path, whose real size and digest the manifest declares.
        """
        path = self.cache_path(role)
        path.parent.mkdir(parents=True, exist_ok=True)
        string = h5py.string_dtype("utf-8")
        with h5py.File(path, "w") as handle:
            for key in keys:
                species = SPECIES_BY_KEY[key]
                numbers = NUMBERS[species]
                n_atoms = len(numbers)
                coords = np.asarray(
                    [[0.7 * index, 0.0, 0.0] for index in range(n_atoms)], dtype=np.float64
                )
                charges = np.asarray(
                    [[0.4 if number == 1 else -0.8] for number in numbers], dtype=np.float64
                )
                group = handle.create_group(key)
                group.create_dataset(
                    "mapped_nonisomeric_smiles", data=SMILES[species], dtype=string
                )
                group.create_dataset("mapped_isomeric_smiles", data=SMILES[species], dtype=string)
                group.create_dataset(
                    "atomic_numbers", data=np.asarray(numbers, dtype=np.int32)[:, None]
                )
                group.create_dataset("coords", data=coords)
                info = group.create_group("mbis_info")
                info.create_dataset("atomic_volumes", data=np.ones((n_atoms, 1)))
                info.create_dataset("atomic_charge", data=charges)
                info.create_dataset("atomic_dipole", data=np.ones((n_atoms, 3)))
                info.create_dataset("atomic_quadrupole", data=np.ones((n_atoms, 3, 3)))
                group.create_dataset(
                    "parameters", data=np.asarray(MBIS_SHELL_ROWS[species], dtype=np.float64)
                )
        return path

    def _write_manifest(self, files: Mapping[str, Path]) -> None:
        """Declare those files, with the size and digest they really have."""
        artifacts = "".join(
            f"  - role: {role}\n"
            f"    filename: {NAME}_{index}.h5\n"
            f"    format: hdf5\n"
            f'    digest: "sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"\n'
            f"    size: {path.stat().st_size}\n"
            f"    locators:\n"
            f"      - fake://{NAME}-{index}\n"
            for index, (role, path) in enumerate(files.items())
        )
        path = self.registry / "dataset" / NAMESPACE / NAME / f"{VERSION}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "schema_version: 1\n"
            "kind: dataset\n"
            f"namespace: {NAMESPACE}\n"
            f"name: {NAME}\n"
            f'version: "{VERSION}"\n'
            "\n"
            f"title: {TITLE}\n"
            f'description: "{DESCRIPTION}"\n'
            f"license: {LICENSE}\n"
            f"doi: {CITATION}\n"
            "\n"
            "artifacts:\n"
            "  - role: index\n"
            f"    filename: {NAME}_dataset.csv\n"
            "    format: csv\n"
            f"    size: {INDEX_SIZE}\n"
            "    locators:\n"
            f"      - fake://{NAME}-index\n"
            f"{artifacts}",
            encoding="utf-8",
        )

    def _write_split_derivation(self) -> None:
        """Write the miniature ``class1-universal-splits/1/`` this home answers from.

        Only the two tables these fences read are written — the mbis uuid one
        and the molecule-level one — and ``metadata.json`` records exactly
        those, because a table is refused unless its own producer's record
        agrees with its bytes.
        """
        root = self.home.joinpath(*SPLIT_SUBPATH)
        root.mkdir(parents=True, exist_ok=True)
        self._write_rows(root / UUID_FILENAME, ("uuid", "identity", "split"), SPLIT_ROWS)
        folded = {identity: split for _, identity, split in SPLIT_ROWS}
        self._write_rows(root / IDENTITY_FILENAME, ("identity", "split"), folded.items())
        metadata = {
            "coordinate": SPLIT_COORDINATE,
            "seed": SPLIT_SEED,
            "ratios": SPLIT_RATIOS,
            "generator": SPLIT_GENERATOR,
            "output_sha256": {
                filename: hashlib.sha256((root / filename).read_bytes()).hexdigest()
                for filename in (UUID_FILENAME, IDENTITY_FILENAME)
            },
        }
        (root / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _write_rows(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> None:
        """Write one gzipped CSV exactly as the split generator writes it."""
        with gzip.open(path, "wt", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(list(header))
            for row in rows:
                writer.writerow(list(row))


@dataclass(frozen=True)
class DocFence:
    """One annotated Python fence of one documentation page.

    Attributes:
        path: The page the fence sits in.
        directive: What the ``<!-- test: … -->`` comment asked for.
        code: The fence body, run verbatim — never rewritten, since what is
            under test is what the reader would paste.
        line: Where the directive comment is, 1-based, so a failure names a
            place an editor can jump to.
    """

    path: Path
    directive: str
    code: str
    line: int

    @property
    def label(self) -> str:
        """``docs/…/page.md:<line>`` — the fence, as a failure should name it."""
        return f"{self.path.relative_to(ROOT)}:{self.line}"

    @property
    def slug(self) -> str:
        """A filesystem-safe form of :attr:`label`, for this fence's own fixture."""
        return self.label.replace("/", "-").replace(":", "-")


def annotated_fences(path: Path, source: str) -> list[DocFence]:
    """Every classified Python fence of *path*, in document order.

    Args:
        path: The documentation page, for the label a failure carries.
        source: That page's text, already read — the same string the
            unclassified-fence count is taken over, so the two cannot disagree.

    Returns:
        One :class:`DocFence` per ``<!-- test: … -->`` comment followed by a
        Python fence.
    """
    return [
        DocFence(
            path=path,
            directive=match.group(1).strip(),
            code=match.group(2),
            line=source.count("\n", 0, match.start()) + 1,
        )
        for match in ANNOTATED.finditer(source)
    ]


def test_documented_python_examples(tmp_path: Path) -> None:
    executed: list[str] = []
    skipped: list[str] = []
    failures: list[str] = []

    for path in sorted(DOCS.rglob("*.md")):
        source = path.read_text(encoding="utf8")
        fences = annotated_fences(path, source)
        assert len(FENCE.findall(source)) == len(fences), (
            f"{path.relative_to(ROOT)} has an unclassified Python fence; "
            "add <!-- test: exec --> or <!-- test: skip reason -->"
        )
        for fence in fences:
            if fence.directive.startswith("skip"):
                skipped.append(f"{fence.label} ({fence.directive})")
                continue
            if fence.directive == "fixture-home":
                fixture = FixtureHome(tmp_path / fence.slug)
                # The fence's own working directory: `prepare(..., output_dir=
                # "blocks/")` is a relative path in one of them, and a refusal
                # that regressed into creating it must not create it in the repo.
                result = subprocess.run(
                    [sys.executable, "-c", fence.code],
                    cwd=fixture.cwd,
                    env={**os.environ, **fixture.env},
                    text=True,
                    capture_output=True,
                    check=False,
                )
            else:
                assert fence.directive == "exec", f"Unknown docs test directive at {fence.label}"
                result = subprocess.run(
                    [sys.executable, "-c", fence.code],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
            if result.returncode == 0:
                executed.append(f"{fence.label} ({fence.directive})")
            else:
                failures.append(f"{fence.label}\n{result.stdout}{result.stderr}")

    print(f"docs Python: {len(executed)} executed, {len(skipped)} skipped")
    for item in executed:
        print(f"PASS {item}")
    for item in skipped:
        print(f"SKIP {item}")
    assert executed, "No executable Python documentation examples were found"
    assert not failures, "\n\n".join(failures)
