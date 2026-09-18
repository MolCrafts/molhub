"""Tests for the Class-I split generator, once it ships inside the wheel.

Mirrors ``src/molhub/scripts/build_class1_splits.py``
(``src/molhub/<area>/<module>.py`` → ``tests/test_<area>/test_<module>.py``,
the same mapping ``src/molhub/dataset/qm9.py`` → ``tests/test_dataset/test_qm9.py``
follows).

**Why it moves out of ``scripts/``.** ``$MOLHUB_HOME/derived/molcrafts/
class1-universal-splits/1/`` is the split assignment every THEMol split view and
every prepared block is routed by, and **nobody publishes it** — it is derived,
on the machine that wants it. So a pip-installed molhub cannot open a single
THEMol split until its user has cloned the repository to reach a file that never
shipped. A derivation the product requires is part of the product:
``python -m molhub.scripts.build_class1_splits`` is the command the refusals name
(:data:`~tests.test_loader.conftest.SPLIT_TABLE_COMMAND`), so it has to exist,
and the repository-root file becomes a shim rather than a second implementation.

**Why it must go through the hub.** The landed script reads its three THEMol
index files straight out of ``$MOLHUB_HOME/files/dataset/themol/<name>@1/index``
and exits 1 if they are not there — a path it built by hand, which only holds
because that is where the fetcher happens to file bytes. Asked through
``Molhub.fetch``, an index already cached costs nothing and one that is missing
is *retrievable*. Retrievable is not the same as free: the three real indexes are
gigabytes, so the default is to say what the download would cost and stop.
``--fetch`` is the reader saying yes. Nothing here goes near the network — the
staged legs serve bytes from ``tmp_path``, and the refusal leg is a refusal.

**The end-to-end leg closes the loop.** Tiny indexes in, generator run, and then
``load_dataset("themol/mbis", split=...)`` over the synthetic shards from
``tests/test_loader/conftest.py`` — reading the very table the generator just
wrote. A generator whose output the loader cannot consume is not a fix for
anything, and only a run that ends in ``load`` can tell.
"""

from __future__ import annotations

import csv
import gzip
import importlib
import importlib.util
import json
import runpy
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import molhub
from molhub.molhub import Molhub
from molhub.registry import Registry

from ..test_loader.conftest import (
    GENERATOR_MODULE,
    HF_IDENTITY,
    HOOH_IDENTITY,
    INDEX_SIZE,
    SHARD_KEYS,
    SPECIES,
    SPECIES_BY_KEY,
    SPLIT_SUBPATH,
    TORSION_SPECIES,
    TORSION_SPECIES_BY_KEY,
    WATER_IDENTITY,
    FakeHub,
    build_registry,
    write_shard,
)

#: The module under test, imported by name inside each test rather than at
#: module scope: it does not exist yet, and a module-level import of it would
#: turn this whole file into one collection error instead of failures with names
#: on them (the rule ``tests/test_loader/conftest.py`` states for its package).
MODULE = GENERATOR_MODULE

#: The repository-root file that becomes a shim. It is not shipped in the wheel,
#: which is exactly why the implementation may not stay in it.
REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SCRIPT = REPO_ROOT / "scripts" / "build_class1_splits.py"

#: The two columns the generator reads out of a THEMol index CSV — the header
#: names of the real files, copied from the landed ``read_index``. The real
#: indexes carry more columns; a generator that needed them would be reading
#: something this fixture cannot stand in for.
INDEX_COLUMNS: tuple[str, str] = ("uuid", "mapped_isomeric_smiles")

#: The three THEMol subsets the derivation is folded from, and the coordinate of
#: each — the ``SOURCES`` table of the generator itself.
SOURCES: Mapping[str, str] = {
    "hessian": "dataset:themol/hessian@1",
    "torsion-scan": "dataset:themol/torsion-scan@1",
    "mbis": "dataset:themol/mbis@1",
}

#: What a full index download costs, from the manifests: one ``index`` role per
#: source at :data:`~tests.test_loader.conftest.INDEX_SIZE` bytes. The refusal
#: has to name this number — "this may download a lot" is not a quantity, and
#: the real one is ~5 GB.
INDEX_DOWNLOAD_SIZE = 3 * INDEX_SIZE

#: The same three manifests with an index size above a kibibyte, and what that
#: total is worth. :data:`INDEX_SIZE` is 101 bytes, whose humanized form is its
#: raw form — ``101 B`` either way — so it cannot tell a rendering through
#: :class:`~molhub.loader.info.ByteSize` apart from a hand-written ``{n} B``.
#: The real indexes are gigabytes, which is the case the notice exists for.
BIG_INDEX_SIZE = 5_000_000
BIG_INDEX_DOWNLOAD_SIZE = 3 * BIG_INDEX_SIZE

#: That total as ``ByteSize`` renders it: 1024-based, one decimal. A literal,
#: never a call into the type under test — a golden that computed itself would
#: agree with any rendering at all.
BIG_INDEX_DOWNLOAD_HUMANIZED = "14.3 MiB"

#: Five molecules that appear in no other fixture, used to pad the hessian index
#: so the identity universe is ten molecules and the 8:1:1 molecule-level split
#: lands non-empty in all three splits. They never reach a shard: the mbis view
#: below reads mbis rows only.
FILLER_ROWS: tuple[tuple[str, str], ...] = (
    ("hess-a", "[H:1][H:2]"),
    ("hess-b", "[F:1][F:2]"),
    ("hess-c", "[Cl:1][Cl:2]"),
    ("hess-d", "[H:1][Cl:2]"),
    ("hess-e", "[H:1][Br:2]"),
)

# ---------------------------------------------------------------------------
# The golden assignment.
#
# Hard-coded, not recomputed: the generator's whole promise is that the same
# inputs and the same seed reproduce the shipped tables byte for byte, and a
# test that re-derived the answer with the code under test would agree with any
# answer. Produced offline by running the landed generator over exactly the
# indexes below:
#
#   MOLHUB_HOME=<tmp> python scripts/build_class1_splits.py --molhub-home <tmp>
#   molhub @ 98e1260, seed 20260814, 2026-08-15
#
# Ten identities, ``n * 8 // 10 = 8`` train and ``n * 1 // 10 = 1`` val, the
# remainder test; the mbis rows land 5 train / 1 val / 0 test.
# ---------------------------------------------------------------------------

MBIS_SPLIT_OF: Mapping[str, str] = {
    "mbis-a": "train",
    "mbis-b": "train",
    "mbis-c": "train",
    "mbis-d": "train",
    "mbis-e": "val",
    "mbis-f": "train",
}

#: The train rows in the order a walk of the two shards visits them.
GOLDEN_TRAIN_KEYS: tuple[str, ...] = ("mbis-a", "mbis-b", "mbis-c", "mbis-d", "mbis-f")
GOLDEN_VAL_KEYS: tuple[str, ...] = ("mbis-e",)

#: What ``.info`` folds out of the generated table. ``test`` is absent because
#: no mbis molecule drew it — the count comes from the rows, not from the ratio.
GOLDEN_COUNTS: Mapping[str, int] = {"train": 5, "val": 1}

#: The molecule-level answer the two tables above were folded from, for the
#: three species the mbis shards hold.
GOLDEN_IDENTITY_SPLIT: Mapping[str, str] = {
    WATER_IDENTITY: "train",
    HOOH_IDENTITY: "train",
    HF_IDENTITY: "val",
}

#: Every file the derivation publishes, as ``molhub.conveyor.splits`` names them.
OUTPUT_FILENAMES: tuple[str, ...] = (
    "identity_splits.csv.gz",
    "hessian_uuid_splits.csv.gz",
    "mbis_uuid_splits.csv.gz",
    "torsion_scan_splits.csv.gz",
)


def index_rows(source: str) -> tuple[tuple[str, str], ...]:
    """The ``uuid, mapped_isomeric_smiles`` rows of one synthetic index.

    The mbis rows are the six records ``tests/test_loader/conftest.py`` writes
    into its two shards, with the SMILES of the species each one is — so the
    uuids the generator assigns are the record keys the loader will look up, and
    the identities it derives are the pinned literals that conftest states.

    Args:
        source: ``hessian``, ``mbis`` or ``torsion-scan``.

    Returns:
        The rows, in file order.
    """
    if source == "mbis":
        return tuple(
            (key, SPECIES[SPECIES_BY_KEY[key]].smiles)
            for keys in SHARD_KEYS.values()
            for key in keys
        )
    if source == "torsion-scan":
        return tuple(
            (key, TORSION_SPECIES[name].smiles) for key, name in TORSION_SPECIES_BY_KEY.items()
        )
    return FILLER_ROWS


def write_index(path: Path, rows: Sequence[tuple[str, str]]) -> Path:
    """Write one THEMol index CSV, with the two columns the generator reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(INDEX_COLUMNS)
        writer.writerows(rows)
    return path


def index_cache_path(home: Path, source: str) -> Path:
    """Where a fetched ``index`` role for *source* lands under *home*.

    Spelled out by hand — ``files/<kind>/<namespace>/<name>@<version>/<role>``
    — for the reason ``tests/test_loader/conftest.py`` spells the ledger path
    out: this layout is the cross-client contract, and a fixture that asked
    production where the bytes are could not tell a wrong path from a right one.
    """
    return home / "files" / "dataset" / "themol" / f"{source}@1" / "index"


class StagedHub:
    """An :class:`~molhub.dataset.hub.ArtifactHub` keyed by coordinate *and* role.

    The generator asks three different coordinates for the same role name, which
    the loader's :class:`~tests.test_loader.conftest.FakeHub` cannot express — it
    serves one role table for whatever coordinate it is handed.

    Args:
        files: Coordinate to role to the local path served for it.
    """

    def __init__(self, files: Mapping[str, Mapping[str, Path]]) -> None:
        self._files = {name: dict(roles) for name, roles in files.items()}
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    @property
    def fetch_count(self) -> int:
        """How many times :meth:`fetch` has been called."""
        return len(self.calls)

    @property
    def coordinates_fetched(self) -> tuple[str, ...]:
        """Every coordinate asked for, in call order, repeats included."""
        return tuple(coordinate for coordinate, _ in self.calls)

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Return the local path of every requested role of *coordinate*."""
        served = self._files[str(coordinate)]
        requested = tuple(roles) if roles is not None else tuple(served)
        missing = [role for role in requested if role not in served]
        if missing:
            raise KeyError(f"{coordinate} has no role {missing}; this hub serves {sorted(served)}")
        self.calls.append((str(coordinate), requested))
        return {role: served[role] for role in requested}


@pytest.fixture
def generator():
    """The generator module, imported when a test asks for it.

    Fails the one test that wanted it — rather than the file — while
    ``molhub.scripts`` does not exist yet.
    """
    return importlib.import_module(MODULE)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Process home pointed at an empty molhub home, no derivation in it."""
    from molhub.config import config

    root = tmp_path / "home"
    root.mkdir()
    previous = config.home_dir
    config.home_dir = root
    yield root
    config.home_dir = previous


@pytest.fixture
def pristine_indexes(tmp_path: Path) -> dict[str, Path]:
    """The three synthetic index files, outside the cache, by source name."""
    root = tmp_path / "indexes"
    return {source: write_index(root / f"{source}.csv", index_rows(source)) for source in SOURCES}


@pytest.fixture
def index_hub(pristine_indexes: dict[str, Path]) -> StagedHub:
    """A hub that *can* serve every index — so refusing to is a choice."""
    return StagedHub(
        {coordinate: {"index": pristine_indexes[source]} for source, coordinate in SOURCES.items()}
    )


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    """A registry declaring all three THEMol sources, ``index`` role included."""
    root = tmp_path / "registry"
    for source in SOURCES:
        build_registry(root, namespace="themol", name=source)
    return Registry.load(root)


@pytest.fixture
def humanizing_registry(tmp_path: Path) -> Registry:
    """The same three sources, declaring index sizes worth humanizing."""
    root = tmp_path / "big-registry"
    for source in SOURCES:
        build_registry(root, namespace="themol", name=source, index_size=BIG_INDEX_SIZE)
    return Registry.load(root)


@pytest.fixture
def staged(home: Path, pristine_indexes: dict[str, Path]) -> Path:
    """The three indexes already in the cache, where a fetch would have put them."""
    for source, path in pristine_indexes.items():
        target = index_cache_path(home, source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    return home


@pytest.fixture
def derivation(home: Path) -> Path:
    """Where the generator files its tables under this home."""
    return home.joinpath(*SPLIT_SUBPATH)


def read_table(path: Path) -> list[dict[str, str]]:
    """Every row of one gzipped output table, as dicts."""
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class TestGeneratorPackaging:
    """The generator is part of the product, not part of the checkout."""

    def test_it_ships_inside_the_package(self):
        """A pip install with no clone must still be able to build the table."""
        assert importlib.util.find_spec(MODULE) is not None

    def test_it_runs_as_a_module(self, monkeypatch: pytest.MonkeyPatch):
        """``python -m molhub.scripts.build_class1_splits`` is what the refusals
        tell the reader to type, so the ``__main__`` entry has to be there."""
        monkeypatch.setattr(sys, "argv", ["build_class1_splits", "--help"])
        with pytest.raises(SystemExit) as raised:
            runpy.run_module(MODULE, run_name="__main__")
        assert raised.value.code == 0

    def test_its_usage_names_the_module_spelling(self, generator, capsys):
        """The usage line is where a reader copies the command from."""
        with pytest.raises(SystemExit):
            generator.main(["--help"])
        assert MODULE in capsys.readouterr().out

    def test_the_repository_script_stays_as_a_shim(self):
        """The old path keeps working — it is in every runbook — by delegating."""
        assert MODULE in LEGACY_SCRIPT.read_text(encoding="utf-8")

    def test_the_repository_script_holds_no_second_implementation(self):
        """Two producers of one derivation drift, and nothing detects it: the
        tables verify against their own metadata, whichever copy wrote them."""
        text = LEGACY_SCRIPT.read_text(encoding="utf-8")
        assert "shuffle" not in text
        assert "identity_splits.csv.gz" not in text


class TestIndexResolution:
    """Where the three input indexes come from, and what asking for them costs."""

    def test_a_cached_index_is_read_without_any_download(
        self, generator, staged: Path, registry, derivation: Path
    ):
        """The hub is a real :class:`~molhub.molhub.Molhub` over locators nothing
        can resolve, so a fetch that actually went out would fail loudly. A cache
        hit short-circuits it, which is what makes re-running the generator free."""
        assert generator.main([], registry=registry, hub=Molhub(registry)) == 0
        assert (derivation / "mbis_uuid_splits.csv.gz").is_file()

    def test_an_absent_index_is_not_silently_downloaded(
        self, generator, home: Path, registry, index_hub: StagedHub
    ):
        """Five gigabytes is not a side effect of running a script."""
        assert generator.main([], registry=registry, hub=index_hub) != 0
        assert index_hub.fetch_count == 0

    def test_the_refusal_names_the_bytes_it_would_have_pulled(
        self, generator, home: Path, registry, index_hub: StagedHub, capsys
    ):
        assert generator.main([], registry=registry, hub=index_hub) != 0
        captured = capsys.readouterr()
        assert str(INDEX_DOWNLOAD_SIZE) in captured.out + captured.err

    def test_the_refusal_humanizes_the_bytes_it_would_have_pulled(
        self, generator, home: Path, humanizing_registry, index_hub: StagedHub, capsys
    ):
        """``5063580160 B`` is a number a reader counts digits on, and this is
        the sentence they weigh before typing ``--fetch``. The library already
        owns the rendering (:class:`~molhub.loader.info.ByteSize`, which
        ``molhub info`` and its stderr notice both print); a second spelling here
        is the drift that shared type exists to end."""
        assert generator.main([], registry=humanizing_registry, hub=index_hub) != 0
        captured = capsys.readouterr()
        assert BIG_INDEX_DOWNLOAD_HUMANIZED in captured.out + captured.err, captured

    def test_the_refusal_keeps_the_raw_byte_count(
        self, generator, home: Path, humanizing_registry, index_hub: StagedHub, capsys
    ):
        """Humanizing is lossy on purpose and the manifest's own number is not:
        a script greps the count, a human reads the unit, and both are answers
        to the same question."""
        assert generator.main([], registry=humanizing_registry, hub=index_hub) != 0
        captured = capsys.readouterr()
        assert str(BIG_INDEX_DOWNLOAD_SIZE) in captured.out + captured.err, captured

    def test_the_refusal_names_the_flag_that_authorises_it(
        self, generator, home: Path, registry, index_hub: StagedHub, capsys
    ):
        """A refusal with no way past it is a wall, not a guard."""
        assert generator.main([], registry=registry, hub=index_hub) != 0
        captured = capsys.readouterr()
        assert "--fetch" in captured.out + captured.err

    def test_the_refusal_writes_no_derivation(
        self, generator, home: Path, registry, index_hub: StagedHub
    ):
        """Fail closed: half a split table routes molecules just as confidently."""
        generator.main([], registry=registry, hub=index_hub)
        assert not (home / "derived").exists()

    def test_fetch_authorises_the_download(
        self, generator, home: Path, registry, index_hub: StagedHub, derivation: Path
    ):
        """With the reader's yes, every source is asked for — and only ``index``."""
        assert generator.main(["--fetch"], registry=registry, hub=index_hub) == 0
        assert sorted(index_hub.coordinates_fetched) == sorted(SOURCES.values())
        assert (derivation / "mbis_uuid_splits.csv.gz").is_file()


class TestGeneratedDerivation:
    """What one run writes, and that the loader can read it back.

    Every number here is the golden from the module header — the landed
    generator's own output over these indexes — so a run that reproduces it is
    reproducing the algorithm, not agreeing with itself.
    """

    @pytest.fixture
    def built(self, generator, staged: Path, registry, derivation: Path) -> Path:
        """One completed run, with the three indexes already cached."""
        assert generator.main([], registry=registry, hub=Molhub(registry)) == 0
        return derivation

    def test_it_writes_every_published_table(self, built: Path):
        assert sorted(path.name for path in built.glob("*.csv.gz")) == sorted(OUTPUT_FILENAMES)

    def test_it_records_the_module_as_its_generator(self, built: Path):
        """``metadata.json``'s ``generator`` is what a table's provenance quotes,
        so it has to name something a reader can run."""
        metadata = json.loads((built / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["generator"] == MODULE

    def test_it_assigns_the_molecule_level_splits_it_always_did(self, built: Path):
        """Identity, not uuid: every conformer of one molecule in one split."""
        rows = read_table(built / "identity_splits.csv.gz")
        assigned = {row["identity"]: row["split"] for row in rows}
        assert {
            identity: assigned[identity] for identity in GOLDEN_IDENTITY_SPLIT
        } == GOLDEN_IDENTITY_SPLIT

    def test_it_assigns_every_mbis_record_the_split_of_its_molecule(self, built: Path):
        rows = read_table(built / "mbis_uuid_splits.csv.gz")
        assert {row["uuid"]: row["split"] for row in rows} == dict(MBIS_SPLIT_OF)

    def test_load_dataset_opens_the_split_this_run_assigned(
        self, built: Path, registry, tmp_path: Path
    ):
        """The loop, closed: the table was built a moment ago by the generator
        under test, and the loader reads it with no other derivation on disk."""
        shards = {
            role: write_shard(tmp_path / "shards" / f"{role}.h5", keys)
            for role, keys in SHARD_KEYS.items()
        }
        ds = molhub.load("themol/mbis", registry=registry, hub=FakeHub(shards))
        view = molhub.SubsetDataset(ds, molhub.assignment(ds)["train"])
        keys = tuple(view[index][0].meta["source_record_id"] for index in range(len(view)))
        assert keys == GOLDEN_TRAIN_KEYS

    def test_load_dataset_opens_the_other_split_too(self, built: Path, registry, tmp_path: Path):
        """One molecule drew ``val``, and it is the one the table says."""
        shards = {
            role: write_shard(tmp_path / "shards" / f"{role}.h5", keys)
            for role, keys in SHARD_KEYS.items()
        }
        ds = molhub.load("themol/mbis", registry=registry, hub=FakeHub(shards))
        view = molhub.SubsetDataset(ds, molhub.assignment(ds)["val"])
        keys = tuple(view[index][0].meta["source_record_id"] for index in range(len(view)))
        assert keys == GOLDEN_VAL_KEYS

    def test_the_builder_counts_what_this_run_assigned(self, built: Path, registry, tmp_path: Path):
        """``.info`` reads the same table, and still costs no shard bytes."""
        shards = {
            role: write_shard(tmp_path / "shards" / f"{role}.h5", keys)
            for role, keys in SHARD_KEYS.items()
        }
        hub = FakeHub(shards)
        from molhub.loader.builder import DatasetBuilder

        info = DatasetBuilder("themol/mbis", registry=registry, hub=hub).info
        assert {split.name: split.num_examples for split in info.splits} == dict(GOLDEN_COUNTS)
        assert hub.fetch_count == 0
