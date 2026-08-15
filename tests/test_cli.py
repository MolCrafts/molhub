"""Tests for the typer command line.

Run in-process through CliRunner rather than as a subprocess, so a failure
shows a Python traceback instead of an exit code.
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from molhub.cli import app

runner = CliRunner()

#: How many bytes each published 3BPA file declares, and what they add up to.
#: Distinct powers-of-ten so a sum that dropped a role cannot match, and large
#: enough that the total reads as a real download rather than a rounding error.
THREEBPA_SIZES: dict[str, int] = {
    "train_300K": 1000000,
    "test_300K": 200000,
    "test_600K": 30000,
    "test_1200K": 4000,
}
THREEBPA_DOWNLOAD_SIZE = 1234000

#: The same total as ``molhub.loader.info.ByteSize`` renders it: 1024-based,
#: one decimal (1234000 / 1048576 = 1.1768…). A literal, not a call into the
#: type under test, for the reason ``tests/test_loader/test_info.py`` states —
#: a golden that computed itself would agree with any rendering at all.
THREEBPA_DOWNLOAD_HUMANIZED = "1.2 MiB"

#: A manifest declaring one role per published 3BPA file, as ``v1.yaml`` does.
#: Written here rather than imported from ``tests/test_loader``: what a CLI test
#: needs from it is the declared *sizes*, and those are this file's fixture.
THREEBPA_MANIFEST = (
    "schema_version: 1\n"
    "kind: dataset\n"
    "namespace: molcrafts\n"
    "name: 3bpa\n"
    'version: "1"\n'
    "\n"
    "title: 3BPA miniature\n"
    'description: "Two-atom-type stand-in for the 3BPA benchmark files."\n'
    "license: MIT\n"
    "doi: 10.1021/acs.jctc.1c00647\n"
    "\n"
    "artifacts:\n"
    + "".join(
        f"  - role: {role}\n"
        f"    filename: {role}.xyz\n"
        f"    format: extxyz\n"
        f"    size: {size}\n"
        f"    locators:\n"
        f"      - fake://3bpa-{role}\n"
        for role, size in THREEBPA_SIZES.items()
    )
    + "\n"
    "targets:\n"
    "  graph_level: [energy]\n"
    "  atom_level: [forces]\n"
)


@pytest.fixture
def idx(registry_dir):
    return ["--registry", str(registry_dir)]


def _words(output: str) -> set[str]:
    """Every whitespace/punctuation-delimited token of *output*.

    Tokens rather than substrings: ``"val"`` must be a word of its own, so a
    rendering that only ever said ``"value"`` cannot pass for one that lists the
    validation split.
    """
    return set(re.findall(r"\w+", output))


def _summary(output: str) -> str:
    """The one-line summary of a ``--help`` screen, unwrapped.

    Typer wraps the docstring's first paragraph to the terminal width and prints
    the option boxes after it, so "the one-liner" is not a line: it is the first
    paragraph of the prose above the first box, joined back together. Read this
    way rather than by line so a test cannot pass because a word happened to
    land past a wrap point.

    Args:
        output: The captured ``--help`` screen.

    Returns:
        The summary sentence, or ``""`` when the screen has no prose at all.
    """
    prose = output.split("╭")[0]
    paragraphs: list[str] = []
    current: list[str] = []
    for raw in prose.splitlines():
        line = raw.strip()
        if line.startswith("Usage:"):
            continue
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs[0] if paragraphs else ""


def _reports(output: str, *, name: str, count: int) -> bool:
    """Whether one line of *output* names *name* and *count* as words of their own."""
    return any(
        re.search(rf"\b{name}\b", line) and re.search(rf"\b{count}\b", line)
        for line in output.splitlines()
    )


class TestSearch:
    def test_lists_matching_artifacts(self, idx):
        result = runner.invoke(app, ["search", "qm9", *idx])
        assert result.exit_code == 0
        assert "dataset:molcrafts/qm9@v2" in result.stdout

    def test_shows_the_title(self, idx):
        assert "QM9" in runner.invoke(app, ["search", *idx]).stdout

    def test_kind_filter(self, idx):
        result = runner.invoke(app, ["search", "--kind", "model", *idx])
        assert result.exit_code == 1

    def test_no_match_exits_nonzero(self, idx):
        assert runner.invoke(app, ["search", "nothing-like-it", *idx]).exit_code == 1

    def test_bare_search_lists_everything(self, idx):
        assert runner.invoke(app, ["search", *idx]).exit_code == 0


class TestInfo:
    """What is in this dataset — content first, transport behind ``--files``.

    ``hf-facade-04-streaming-prepare`` ac-006 moved the artifact table behind a
    flag and made the body of ``info`` come from ``DatasetBuilder.info``, the
    content authority, rather than from a second Manifest-only rendering. The
    three assertions that pinned roles, digests and locators in the bare output
    therefore moved to ``--files`` instead of being dropped: they are still the
    right claims, about the other view. ``molhub info qm9`` used to exit 1 as a
    malformed coordinate and now resolves as a HuggingFace-spelled name, so the
    refusal is pinned on a name the registry genuinely does not declare.

    The THEMol fixture below is where the *content* half is checked, because it
    is the one with a description, features and a table-backed split count.
    """

    @pytest.fixture
    def themol(self, tmp_path, monkeypatch):
        """``dataset:themol/mbis@1`` declared, its split derivation filed, hub sealed.

        ``info`` staying fetch-free is a feature, not an accident, so the hub's
        one verb is made an error for the duration: a rendering that reached for
        shard bytes to print an example record fails here rather than merely
        being slow on a 28.9 GiB artifact.
        """
        from molhub.molhub import Molhub

        from .test_loader.conftest import SPLIT_SUBPATH, build_registry, write_split_derivation

        root = tmp_path / "registry"
        build_registry(root)
        write_split_derivation(tmp_path.joinpath("home", *SPLIT_SUBPATH))
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "home"))

        def refuse(self, coordinate, *, roles=None):
            raise AssertionError(
                f"`molhub info` fetched {coordinate} roles={roles!r}; info is fetch-free."
            )

        monkeypatch.setattr(Molhub, "fetch", refuse)
        return ["--registry", str(root)]

    @pytest.fixture
    def undeclared(self, tmp_path):
        """A registry holding one artifact molhub ships no reader for.

        ``molhub info qm9@v2`` is no longer free: qm9's whole content is one
        view now (re-evaluation, ruling 1) and counting it means reading the
        tarball, so describing it goes through the hub. The tests below are
        about the *rendering* — coordinate, license, doi, declared targets, and
        the transport table behind ``--files`` — which is the same for every
        artifact, so they are pinned on one with the same manifest shape and no
        declaration entry behind it. What qm9 now costs at the terminal is
        pinned where it belongs, in :class:`TestInfoOnAWholeViewDataset`.
        """
        from .conftest import manifest_yaml

        root = tmp_path / "undeclared-registry"
        path = root / "dataset" / "molcrafts" / "fixture-only" / "v2.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(manifest_yaml(name="fixture-only"), encoding="utf-8")
        return ["--registry", str(root)]

    def test_prints_the_coordinate(self, undeclared):
        result = runner.invoke(app, ["info", "fixture-only@v2", *undeclared])
        assert result.exit_code == 0, result.output
        assert "dataset:molcrafts/fixture-only@v2" in result.stdout

    def test_prints_license_and_citation(self, undeclared):
        out = runner.invoke(app, ["info", "fixture-only@v2", *undeclared]).stdout
        assert "CC0-1.0" in out
        assert "10.1038/sdata.2014.22" in out

    def test_files_prints_every_artifact_role(self, undeclared):
        out = runner.invoke(app, ["info", "fixture-only@v2", "--files", *undeclared]).stdout
        assert "[main]" in out and "[exclude]" in out

    def test_files_prints_the_digest_and_locators(self, undeclared):
        out = runner.invoke(app, ["info", "fixture-only@v2", "--files", *undeclared]).stdout
        assert "md5:" in out
        assert "fake://main-backup" in out

    def test_prints_declared_targets(self, undeclared):
        assert "U0" in runner.invoke(app, ["info", "fixture-only@v2", *undeclared]).stdout

    def test_unknown_coordinate_exits_nonzero(self, idx):
        assert runner.invoke(app, ["info", "qm9@v9", *idx]).exit_code == 1

    def test_an_undeclared_name_exits_nonzero(self, idx):
        assert runner.invoke(app, ["info", "molcrafts/not-a-dataset", *idx]).exit_code == 1

    # -- ac-006: content first, roles behind a flag -------------------------

    def test_a_name_without_a_version_resolves(self, themol):
        """The HuggingFace spelling ac-006 is written in: no ``@version``."""
        assert runner.invoke(app, ["info", "themol/mbis", *themol]).exit_code == 0

    def test_it_prints_the_description(self, themol):
        from .test_loader.conftest import DESCRIPTION

        assert DESCRIPTION in runner.invoke(app, ["info", "themol/mbis", *themol]).output

    def test_it_prints_the_features(self, themol):
        """What a record carries — the answer to 「shard-000 是什么东西」."""
        out = runner.invoke(app, ["info", "themol/mbis", *themol]).output
        assert "atomic_charge" in out

    def test_it_prints_every_split(self, themol):
        out = runner.invoke(app, ["info", "themol/mbis", *themol]).output
        assert {"train", "val", "test"} <= _words(out)

    def test_it_prints_the_count_of_a_split(self, themol):
        """Three train rows, from one gzipped table and no shard bytes at all."""
        out = runner.invoke(app, ["info", "themol/mbis", *themol]).output
        assert _reports(out, name="train", count=3), out

    def test_it_prints_no_artifact_role(self, themol):
        out = runner.invoke(app, ["info", "themol/mbis", *themol]).output
        assert "shard-000" not in out
        assert "shard-001" not in out

    def test_it_prints_no_filename(self, themol):
        out = runner.invoke(app, ["info", "themol/mbis", *themol]).output
        assert "mbis_0.h5" not in out

    # -- the download line, in a form a reader can weigh --------------------
    #
    # `download   31041658614 B` is a number to count digits on; the same fact
    # reads `28.9 GiB` and tells a reader whether to run this on a laptop. The
    # raw count stays, in parentheses: it is what a script greps and what the
    # manifest actually declares, and dropping it would trade one audience for
    # another. The rendering is `molhub.loader.info.ByteSize`, the same type
    # `DatasetInfo.__str__` prints — two renderings of one number is exactly the
    # drift a shared type prevents.

    def _download_line(self, output: str) -> str:
        """The one line of ``info``'s report that states the download size."""
        matches = [line for line in output.splitlines() if "download" in line]
        assert len(matches) == 1, output
        return matches[0]

    def test_the_download_line_is_humanized(self, themol):
        """11 101 bytes of fixture manifest, 1024-based: ``10.8 KiB``."""
        out = runner.invoke(app, ["info", "themol/mbis", *themol]).stdout
        assert "10.8 KiB" in self._download_line(out), out

    def test_the_download_line_keeps_the_raw_byte_count(self, themol):
        """In parentheses, because a script greps the number and a human reads
        the unit; the manifest declares the number, so it stays verbatim."""
        from .test_loader.conftest import DOWNLOAD_SIZE

        line = self._download_line(runner.invoke(app, ["info", "themol/mbis", *themol]).stdout)
        assert re.search(rf"\(\D*{DOWNLOAD_SIZE}\b", line), line

    def test_the_download_line_reports_one_size_twice_and_not_two_sizes(self, themol):
        """The humanized form and the raw count are the same fact, on one line."""
        line = self._download_line(runner.invoke(app, ["info", "themol/mbis", *themol]).stdout)
        assert "10.8 KiB" in line and "11101" in line, line

    def test_the_cli_renders_bytes_through_the_librarys_own_type(self):
        """One rendering, not two that agree today: the same promotion
        ``default_ledger_path`` and ``DEFAULT_BUDGET_BYTES`` already had."""
        from pathlib import Path

        import molhub

        source = (Path(molhub.__file__).parent / "cli.py").read_text(encoding="utf-8")
        assert "ByteSize" in source

    def test_files_prints_the_roles(self, themol):
        out = runner.invoke(app, ["info", "themol/mbis", "--files", *themol]).output
        assert "shard-000" in out and "shard-001" in out

    def test_files_prints_filenames_and_sizes(self, themol):
        out = runner.invoke(app, ["info", "themol/mbis", "--files", *themol]).output
        assert "mbis_0.h5" in out
        assert "1000" in out

    def test_files_prints_locators(self, themol):
        out = runner.invoke(app, ["info", "themol/mbis", "--files", *themol]).output
        assert "fake://mbis-0" in out

    def test_files_still_prints_the_content_first(self, themol):
        """``--files`` adds the transport view; it does not become the report."""
        from .test_loader.conftest import DESCRIPTION

        out = runner.invoke(app, ["info", "themol/mbis", "--files", *themol]).output
        assert out.index(DESCRIPTION) < out.index("shard-000")

    # -- reachability: what `info` costs, and where it looks ---------------
    #
    # `info` is free for a table-backed dataset and costs the whole artifact for
    # one whose class owns its splits — that asymmetry is documented in
    # `cli.py`'s module docstring and invisible at the terminal. A verb that
    # sometimes downloads a benchmark has to say so before it does, not in a
    # docstring the caller is not reading.

    @pytest.fixture
    def threebpa(self, tmp_path, monkeypatch):
        """``dataset:molcrafts/3bpa@1`` declared, four published files, hub sealed.

        The one remaining declared-split dataset: counting its splits means
        reading its files, so ``info`` on it is a download. The hub's one verb is
        made an error for the duration, so *whatever* is printed before the
        attempt is all the warning a reader would have got.
        """
        from molhub.molhub import Molhub

        root = tmp_path / "3bpa-registry"
        path = root / "dataset" / "molcrafts" / "3bpa" / "1.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(THREEBPA_MANIFEST, encoding="utf-8")
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "home"))

        def refuse(self, coordinate, *, roles=None):
            raise AssertionError(f"`molhub info` fetched {coordinate} roles={roles!r}.")

        monkeypatch.setattr(Molhub, "fetch", refuse)
        return ["--registry", str(root)]

    def test_it_says_what_describing_will_cost_before_it_fetches(self, threebpa):
        """The notice is on stderr, so a piped report is unchanged by it."""
        result = runner.invoke(app, ["info", "molcrafts/3bpa", *threebpa])
        assert "download" in result.stderr.lower()

    def test_the_notice_names_the_bytes_it_is_about_to_pull(self, threebpa):
        """A warning without a number is one nobody can weigh: 1.2 MB here, 4 GB
        for the real benchmark. The byte total is the manifest's own sum, and it
        is what the report itself prints once it gets that far."""
        result = runner.invoke(app, ["info", "molcrafts/3bpa", *threebpa])
        assert str(THREEBPA_DOWNLOAD_SIZE) in result.stderr

    def test_the_notice_humanizes_the_bytes_it_is_about_to_pull(self, threebpa):
        """The notice is the *other* place this file renders a byte count, and it
        keeps a hand-written ``{size} B`` while the report line above renders the
        same fact through ``ByteSize``. Two spellings of one number in one module
        is exactly the drift the shared type was introduced to end — and this is
        the spelling that matters most, because it is the one a reader weighs
        *before* deciding whether to let the command spend the bytes. Four GB of
        real benchmark reads as ``4116013056``, which nobody sizes at a glance."""
        result = runner.invoke(app, ["info", "molcrafts/3bpa", *threebpa])
        assert THREEBPA_DOWNLOAD_HUMANIZED in result.stderr, result.stderr

    def test_the_notice_keeps_the_raw_byte_count_in_parentheses(self, threebpa):
        """Strengthening, not replacing: the pin two tests up stays exactly as it
        was, and this says *where* the raw count now sits. Same shape as the
        report's own download line — humanized for the human, the manifest's own
        number in parentheses for the script and for anyone reconciling it
        against the manifest."""
        result = runner.invoke(app, ["info", "molcrafts/3bpa", *threebpa])
        assert re.search(rf"\(\D*{THREEBPA_DOWNLOAD_SIZE}\b", result.stderr), result.stderr

    def test_the_help_warns_that_describing_can_download(self):
        """``--help`` is where a reader looks *before* typing the command."""
        result = runner.invoke(app, ["info", "--help"])
        assert result.exit_code == 0
        assert "download" in result.output.lower()

    def test_home_selects_the_cache_root_the_split_table_is_read_from(self, tmp_path, monkeypatch):
        """Parity with ``cache status`` / ``cache verify``, which have taken
        ``--home`` all along: the derivation ``info`` reads lives under it, and
        with only ``$MOLHUB_HOME`` to go on there is no way to point this verb at
        a second molhub home without exporting a variable around it."""
        from .test_loader.conftest import SPLIT_SUBPATH, build_registry, write_split_derivation

        root = tmp_path / "registry"
        build_registry(root)
        home = tmp_path / "elsewhere"
        write_split_derivation(home.joinpath(*SPLIT_SUBPATH))
        # The environment points somewhere with no derivation in it, so a pass
        # here can only mean the option was read.
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "empty-home"))

        result = runner.invoke(
            app, ["info", "themol/mbis", "--home", str(home), "--registry", str(root)]
        )
        assert result.exit_code == 0, result.output
        assert _reports(result.output, name="train", count=3), result.output

    def test_a_bare_namespace_suggests_the_full_names_under_it(self, themol):
        """``molhub info themol`` reads as "tell me about themol" and resolves as
        ``molcrafts/themol``, which nothing declares. The registry knows perfectly
        well what that namespace holds, so the refusal can hand it over instead of
        reporting a coordinate the user never typed."""
        result = runner.invoke(app, ["info", "themol", *themol])
        assert result.exit_code == 1
        assert "themol/mbis" in result.output
        assert "Traceback" not in result.output

    def test_a_missing_split_table_names_the_command_that_builds_it(self, tmp_path, monkeypatch):
        """The first-run state, at the terminal: nothing publishes the split
        derivation, so ``info`` on a THEMol dataset fails on a machine that has
        never built one — and the only useful reply is the command that does."""
        from .test_loader.conftest import SPLIT_TABLE_COMMAND, build_registry

        root = tmp_path / "registry"
        build_registry(root)
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "empty-home"))

        result = runner.invoke(app, ["info", "themol/mbis", "--registry", str(root)])
        assert result.exit_code == 1
        assert SPLIT_TABLE_COMMAND in result.output
        assert "Traceback" not in result.output


class TestFetch:
    @pytest.fixture(autouse=True)
    def offline_source(self, monkeypatch, bodies, tmp_path):
        """Serve the fixture bytes through a fake driver; never touch the network."""
        from molhub.sources import BlobStore, Drivers, Fetcher

        from .test_sources.conftest import FakeSource

        real_init = Fetcher.__init__

        def _patched(self, *, drivers=None, blobs=None):
            real_init(
                self,
                drivers=drivers or Drivers.of(FakeSource(bodies=bodies)),
                blobs=blobs or BlobStore(root=tmp_path / "home"),
            )

        monkeypatch.setattr(Fetcher, "__init__", _patched)

    def test_reports_a_path_per_role(self, idx):
        result = runner.invoke(app, ["fetch", "qm9@v2", *idx])
        assert result.exit_code == 0
        assert "main\t" in result.stdout and "exclude\t" in result.stdout

    def test_into_copies_files_out_under_their_manifest_names(self, idx, tmp_path):
        target = tmp_path / "out"
        result = runner.invoke(app, ["fetch", "qm9@v2", "--into", str(target), *idx])
        assert result.exit_code == 0
        assert (target / "qm9.tar.bz2").exists()
        assert (target / "excluded.txt").exists()

    def test_unknown_coordinate_exits_nonzero(self, idx):
        assert runner.invoke(app, ["fetch", "qm9@v9", *idx]).exit_code == 1


class TestCacheVerify:
    """Verify re-checks cached files against the digests their manifests name."""

    def _cache(self, home, body: bytes) -> None:
        from molhub.coordinate import Coordinate
        from molhub.sources import BlobStore

        # Build the key the way production does. Spelling it out by hand here
        # is what let `cache verify` and `fetch` agree on a path that violated
        # the documented layout.
        key = f"{Coordinate.parse('qm9@v2').cache_path()}/main"
        path = BlobStore(root=home).path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def test_reports_an_empty_cache(self, idx, tmp_path):
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path), *idx])
        assert result.exit_code == 0
        assert "Nothing cached" in result.stdout

    def test_passes_on_an_intact_file(self, idx, tmp_path):
        from .conftest import MAIN_BODY

        self._cache(tmp_path, MAIN_BODY)
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path), *idx])
        assert result.exit_code == 0
        assert "0 stale" in result.stdout

    def test_detects_a_file_that_no_longer_matches(self, idx, tmp_path):
        self._cache(tmp_path, b"a different version")
        result = runner.invoke(app, ["cache", "verify", "--home", str(tmp_path), *idx])
        assert result.exit_code == 1
        assert "1 stale" in result.stdout

    def test_counts_files_whose_manifest_has_no_digest(self, tmp_path, registry_dir):
        """Nothing published means nothing to check — say so, do not pretend."""
        from .conftest import MAIN_MD5

        # Only `main` loses its digest — it is the role `_cache` writes, and it
        # carries a `size`, which every artifact needs when no digest is
        # published. Stripping every digest in the file would leave `exclude`
        # with no cross-check at all, and the manifest would not load.
        manifest = registry_dir / "dataset" / "molcrafts" / "qm9" / "v2.yaml"
        manifest.write_text(manifest.read_text().replace(f'    digest: "md5:{MAIN_MD5}"\n', ""))
        self._cache(tmp_path, b"anything at all")
        result = runner.invoke(
            app, ["cache", "verify", "--home", str(tmp_path), "--registry", str(registry_dir)]
        )
        assert result.exit_code == 0
        assert "1 without a published digest" in result.stdout


class TestCacheStatus:
    """Residency, printed: one line per conveyor tier, exit 1 over a budget.

    The tier paths are spelled out by hand for the same reason
    ``TestCacheVerify._cache`` spells the blob key out: ``conveyor/raw`` and
    ``conveyor/blocks`` (never under ``files/``) are the layout contract, and a
    test that asked production where to write could not tell a wrong layout from
    a right one. Assertions read ``result.output`` so a message the command
    chooses to send to stderr still counts.
    """

    def _entry(self, home, tier: str, block_id: str, body: bytes) -> None:
        """File *body* as one tier entry of ``dataset:themol/mbis@1``."""
        from molhub.conveyor.block import BlockId

        key = BlockId("dataset:themol/mbis@1", "electrostatic", None, block_id).key()
        path = home / "conveyor" / tier / key / "column.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)

    def _both_tiers(self, home) -> None:
        """1 024 B resident in the raw tier, 4 096 B in the blocks tier."""
        self._entry(home, "raw", "shard-000", b"\0" * 1024)
        self._entry(home, "blocks", "shard-001", b"\0" * 4096)

    def _line(self, output: str, tier: str) -> str:
        """The one line *tier* reports itself on."""
        matches = [line for line in output.splitlines() if line.strip().startswith(tier)]
        assert matches, output
        return matches[0]

    def _invoke(self, home, *, budget_blocks: int = 8192):
        return runner.invoke(
            app,
            [
                "cache",
                "status",
                "--home",
                str(home),
                "--budget-raw",
                "2048",
                "--budget-blocks",
                str(budget_blocks),
            ],
        )

    def test_reports_an_empty_root(self, tmp_path):
        result = runner.invoke(app, ["cache", "status", "--home", str(tmp_path)])
        assert result.exit_code == 0
        assert f"No conveyor tiers under {tmp_path}." in result.output

    def test_prints_one_line_per_tier(self, tmp_path):
        self._both_tiers(tmp_path)
        output = self._invoke(tmp_path).output
        assert self._line(output, "raw")
        assert self._line(output, "blocks")

    def test_a_tier_line_carries_its_entry_count(self, tmp_path):
        self._both_tiers(tmp_path)
        assert re.search(r"\b1\b", self._line(self._invoke(tmp_path).output, "blocks"))

    def test_a_tier_line_carries_its_resident_bytes(self, tmp_path):
        self._both_tiers(tmp_path)
        assert "4096" in self._line(self._invoke(tmp_path).output, "blocks")

    def test_a_tier_line_carries_its_budget_bytes(self, tmp_path):
        self._both_tiers(tmp_path)
        assert "8192" in self._line(self._invoke(tmp_path).output, "blocks")

    def test_the_two_tiers_report_their_own_budgets(self, tmp_path):
        """ac-002 at the surface: two budgets, never one shared number."""
        self._both_tiers(tmp_path)
        line = self._line(self._invoke(tmp_path).output, "raw")
        assert "1024" in line and "2048" in line

    def test_tiers_within_their_budgets_exit_zero(self, tmp_path):
        self._both_tiers(tmp_path)
        assert self._invoke(tmp_path).exit_code == 0

    def test_a_tier_over_its_budget_exits_nonzero(self, tmp_path):
        """I4 failing on disk is what this exit code means."""
        self._both_tiers(tmp_path)
        assert self._invoke(tmp_path, budget_blocks=1024).exit_code == 1


class TestCacheCoverage:
    """What the run can prove it saw — and a refusal when it cannot prove it.

    The ledger is written where the conveyor keeps its own bookkeeping,
    ``<home>/conveyor/ledger.jsonl``, alongside the two tier directories.
    """

    def _ledger(self, home) -> None:
        """One shard fetched, prepared, consumed and reclaimed; one block evicted."""
        from molhub.conveyor import BlockId, BlockState, Ledger

        ledger = Ledger(home / "conveyor" / "ledger.jsonl", actor="plan:test")
        shard = BlockId("dataset:themol/mbis@1", "electrostatic", None, "shard-000")
        block = BlockId("dataset:themol/mbis@1", "electrostatic", "train", "block-000")
        ledger.append(shard, BlockState.REMOTE)
        ledger.append(shard, BlockState.DOWNLOADING, size_bytes=640)
        ledger.append(shard, BlockState.READY, size_bytes=512)
        ledger.append(shard, BlockState.CONSUMED)
        ledger.append(shard, BlockState.REMOTE, size_bytes=512)
        ledger.append(block, BlockState.READY, size_bytes=384)
        ledger.append(block, BlockState.REMOTE, size_bytes=384)

    def _invoke(self, home):
        """Run against the bundled registry — the roster's production source."""
        return runner.invoke(app, ["cache", "coverage", "--home", str(home)])

    def test_a_missing_roster_exits_nonzero(self, tmp_path):
        """I10: a coverage number without the corpus denominator is implicit coverage."""
        empty = tmp_path / "registry"
        empty.mkdir()
        self._ledger(tmp_path)
        result = runner.invoke(
            app, ["cache", "coverage", "--home", str(tmp_path), "--registry", str(empty)]
        )
        assert result.exit_code == 1

    def test_a_missing_roster_says_so(self, tmp_path):
        empty = tmp_path / "registry"
        empty.mkdir()
        self._ledger(tmp_path)
        result = runner.invoke(
            app, ["cache", "coverage", "--home", str(tmp_path), "--registry", str(empty)]
        )
        assert "roster" in result.output.lower()
        assert "Traceback" not in result.output

    def test_it_reports_the_blocks_seen(self, tmp_path):
        self._ledger(tmp_path)
        result = self._invoke(tmp_path)
        assert result.exit_code == 0
        assert "blocks" in result.output.lower()

    def test_it_reports_the_consumed_share_of_the_corpus(self, tmp_path):
        self._ledger(tmp_path)
        assert "%" in self._invoke(tmp_path).output

    def test_it_reports_the_units_seen(self, tmp_path):
        self._ledger(tmp_path)
        assert "units" in self._invoke(tmp_path).output.lower()

    def test_it_reports_the_downloaded_bytes(self, tmp_path):
        """A retried fetch counts twice; this ledger fetched once, for 640 B."""
        self._ledger(tmp_path)
        assert "640" in self._invoke(tmp_path).output

    def test_it_reports_the_prepared_bytes(self, tmp_path):
        self._ledger(tmp_path)
        assert "896" in self._invoke(tmp_path).output

    def test_it_reports_the_evicted_bytes(self, tmp_path):
        """Only the derived block counts here; the raw shard's 512 B is the I3 reclaim."""
        self._ledger(tmp_path)
        assert "384" in self._invoke(tmp_path).output


class TestBrokenRegistry:
    def test_a_malformed_manifest_is_a_clean_error(self, tmp_path):
        bad = tmp_path / "dataset" / "molcrafts" / "x" / "1.yaml"
        bad.parent.mkdir(parents=True)
        bad.write_text("schema_version: 1\n")
        result = runner.invoke(app, ["search", "--registry", str(tmp_path)])
        assert result.exit_code != 0
        assert "Traceback" not in result.stdout


class TestCacheHelpText:
    """``--help`` is written for the person who has not read the source.

    ``molhub cache status`` reports how much disk the local cache is holding
    against a budget. What it *says* is "Report each conveyor tier's residency
    against its own byte budget" — three words of internal vocabulary in a
    sentence of nine. "Conveyor" is a molhub implementation noun that appears
    nowhere in the product's own documentation of what a cache is; "residency"
    and "tier" are the streaming design's words for "how much is on disk" and
    "which pile it is in". A user scanning ``molhub cache --help`` to find out
    whether this command is the one they want cannot tell from it.

    The pin is deliberately one-sided: the *one-liners* — what the subcommand
    listing shows, and the first paragraph of each screen — must be plain, and
    the byte budget the verb is actually about must be named in plain words. The
    option help for ``--budget-raw`` may still say which tier it bounds, because
    that flag genuinely addresses one, and the report's own lines are not help
    text at all.
    """

    def _help(self, *command: str) -> str:
        result = runner.invoke(app, [*command, "--help"])
        assert result.exit_code == 0, result.output
        return result.output

    def test_the_status_summary_does_not_say_conveyor(self):
        """A word for molhub's own plumbing, in the first sentence a user reads."""
        assert "conveyor" not in _summary(self._help("cache", "status")).lower()

    def test_the_status_summary_does_not_say_tier(self):
        """ "Tier" is the streaming design's word for a pile of cached files; the
        report below prints one line per pile and names each of them, which is
        where a reader can learn it from an example instead of a definition."""
        assert "tier" not in _summary(self._help("cache", "status")).lower()

    def test_the_status_summary_says_what_it_is_about(self):
        """Dropping the jargon must not drop the meaning: the verb is about a
        budget in bytes, and the summary is where that is stated."""
        assert "budget" in _summary(self._help("cache", "status")).lower()

    def test_the_status_help_names_the_byte_budget_in_plain_words(self):
        assert "byte budget" in self._help("cache", "status").lower()

    def test_the_status_help_never_says_conveyor(self):
        """Not just the summary: the body says "conveyor tier" too, and a reader
        who read past the first line is the one who was trying hardest."""
        assert "conveyor" not in self._help("cache", "status").lower()

    def test_the_coverage_summary_does_not_say_conveyor(self):
        assert "conveyor" not in _summary(self._help("cache", "coverage")).lower()

    def test_the_coverage_summary_does_not_say_tier(self):
        assert "tier" not in _summary(self._help("cache", "coverage")).lower()

    def test_the_subcommand_listing_carries_no_jargon(self):
        """What ``molhub cache --help`` shows is the summaries above, side by
        side — the one screen a user reads before choosing a verb."""
        listing = self._help("cache").lower()
        assert "conveyor" not in listing, listing


class TestTheDownloadNoticeIsPrintedOnce:
    """One warning per command, now that the library prints one too.

    The re-evaluation gives ``DatasetBuilder.info`` the stderr notice this verb
    has had since the reachability wave (ruling 2): the Python API is what a
    notebook calls, and it surprised people. Two layers stating the same
    sentence is one notice printed twice at the terminal — which is how a
    warning becomes noise, and noise is how the real one gets skipped.
    """

    def test_the_notice_appears_exactly_once(self, tmp_path, monkeypatch):
        """Counted on the humanized size, so the raw count on the report's own
        download line — a different stream and a different sentence — cannot be
        mistaken for a second notice."""
        from molhub.molhub import Molhub

        root = tmp_path / "3bpa-registry"
        path = root / "dataset" / "molcrafts" / "3bpa" / "1.yaml"
        path.parent.mkdir(parents=True)
        path.write_text(THREEBPA_MANIFEST, encoding="utf-8")
        monkeypatch.setenv("MOLHUB_HOME", str(tmp_path / "home"))

        def refuse(self, coordinate, *, roles=None):
            raise AssertionError(f"`molhub info` fetched {coordinate} roles={roles!r}.")

        monkeypatch.setattr(Molhub, "fetch", refuse)
        result = runner.invoke(app, ["info", "molcrafts/3bpa", "--registry", str(root)])
        assert result.stderr.count(THREEBPA_DOWNLOAD_HUMANIZED) == 1, result.stderr


class TestInfoOnAWholeViewDataset:
    """What ``molhub info qm9`` costs now, said before it is spent.

    qm9 declares no split of its own, so its entire content is served as
    ``train`` (re-evaluation, ruling 1) — and the count of that split is the
    dataset's own ``len``, which means reading the 86 MB tarball. That is the
    price of a dataset nobody published a split table for, and it is the same
    price 3BPA already pays; what makes it acceptable is that the verb says so
    on stderr first, and that a reader who does not want to spend it can stop.

    The fixture registry's locators resolve to nothing, so this is also the
    honest shape of the failure: the notice, then a clean refusal, and no
    traceback.
    """

    def test_it_says_what_describing_will_cost(self, idx):
        result = runner.invoke(app, ["info", "qm9@v2", *idx])
        assert "download" in result.stderr.lower(), result.stderr

    def test_the_notice_names_the_declared_bytes(self, idx):
        """19 B of fixture manifest — the sum the report itself would print."""
        result = runner.invoke(app, ["info", "qm9@v2", *idx])
        assert "19" in result.stderr, result.stderr

    def test_a_dataset_whose_bytes_cannot_be_had_exits_nonzero(self, idx):
        """The fixture publishes ``fake://`` locators and this run has no driver
        for them, which is what "the mirror is down" looks like from here."""
        assert runner.invoke(app, ["info", "qm9@v2", *idx]).exit_code == 1

    def test_that_failure_is_not_a_traceback(self, idx):
        """Transport failures have been a clean exit on every other verb since
        the beginning; describing a dataset that now downloads is not the place
        to start printing stack frames at users."""
        assert "Traceback" not in runner.invoke(app, ["info", "qm9@v2", *idx]).output
