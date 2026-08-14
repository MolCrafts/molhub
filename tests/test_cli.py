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


@pytest.fixture
def idx(registry_dir):
    return ["--registry", str(registry_dir)]


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
    def test_prints_the_coordinate(self, idx):
        result = runner.invoke(app, ["info", "qm9@v2", *idx])
        assert result.exit_code == 0
        assert "dataset:molcrafts/qm9@v2" in result.stdout

    def test_prints_license_and_citation(self, idx):
        out = runner.invoke(app, ["info", "qm9@v2", *idx]).stdout
        assert "CC0-1.0" in out
        assert "10.1038/sdata.2014.22" in out

    def test_prints_every_artifact_role(self, idx):
        out = runner.invoke(app, ["info", "qm9@v2", *idx]).stdout
        assert "[main]" in out and "[exclude]" in out

    def test_prints_the_digest_and_locators(self, idx):
        out = runner.invoke(app, ["info", "qm9@v2", *idx]).stdout
        assert "md5:" in out
        assert "fake://main-backup" in out

    def test_prints_declared_targets(self, idx):
        assert "U0" in runner.invoke(app, ["info", "qm9@v2", *idx]).stdout

    def test_unknown_coordinate_exits_nonzero(self, idx):
        assert runner.invoke(app, ["info", "qm9@v9", *idx]).exit_code == 1

    def test_malformed_coordinate_exits_nonzero(self, idx):
        assert runner.invoke(app, ["info", "qm9", *idx]).exit_code == 1


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
