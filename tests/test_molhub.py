"""Tests for the Molhub facade.

The point of most of these is that Molhub *composes* — it must not resolve or
verify anything itself, or the digest guarantee would exist twice.
"""

from __future__ import annotations

import pytest

from molhub import Molhub
from molhub.coordinate import InvalidCoordinate
from molhub.index import UnknownArtifact
from molhub.registry import AllLocatorsFailed, BlobStore, Drivers, Fetcher

from .conftest import MAIN_BODY, SIDE_BODY
from .test_registry.conftest import FakeRegistry


@pytest.fixture
def hub(index_dir, bodies, tmp_path):
    fake = FakeRegistry(bodies=bodies)
    fetcher = Fetcher(drivers=Drivers.of(fake), blobs=BlobStore(root=tmp_path / "home"))
    hub = Molhub(index_dir, fetcher=fetcher)
    hub.registry_stub = fake  # type: ignore[attr-defined]
    return hub


class TestResolve:
    def test_full_coordinate(self, hub):
        assert hub.resolve("dataset:molcrafts/qm9@v2").title.startswith("QM9")

    def test_shorthand(self, hub):
        assert hub.resolve("qm9@v2").coordinate.canonical == "dataset:molcrafts/qm9@v2"

    def test_malformed_coordinate(self, hub):
        with pytest.raises(InvalidCoordinate):
            hub.resolve("qm9")

    def test_unknown_coordinate(self, hub):
        with pytest.raises(UnknownArtifact):
            hub.resolve("qm9@v9")

    def test_resolve_does_not_download(self, hub):
        hub.resolve("qm9@v2")
        assert hub.registry_stub.network_calls == 0


class TestFetch:
    def test_returns_every_role(self, hub):
        assert set(hub.fetch("qm9@v2")) == {"main", "exclude"}

    def test_contents_are_correct(self, hub):
        paths = hub.fetch("qm9@v2")
        assert paths["main"].read_bytes() == MAIN_BODY
        assert paths["exclude"].read_bytes() == SIDE_BODY

    def test_roles_can_be_narrowed(self, hub):
        assert set(hub.fetch("qm9@v2", roles=["main"])) == {"main"}

    def test_narrowing_avoids_the_other_transfer(self, hub):
        hub.fetch("qm9@v2", roles=["main"])
        assert hub.registry_stub.network_calls == 1

    def test_unknown_role(self, hub):
        with pytest.raises(KeyError, match="nope"):
            hub.fetch("qm9@v2", roles=["nope"])

    def test_second_fetch_uses_the_cache(self, hub):
        first = hub.fetch("qm9@v2")
        calls = hub.registry_stub.network_calls
        assert hub.fetch("qm9@v2") == first
        assert hub.registry_stub.network_calls == calls

    def test_files_land_under_their_coordinate(self, hub):
        path = hub.fetch("qm9@v2")["main"]
        assert "qm9@v2" in str(path) and path.name == "main"


class TestFetchDelegatesVerification:
    """If Molhub checked digests itself, the rule would have two homes."""

    def test_wrong_bytes_are_rejected(self, index_dir, tmp_path):
        fake = FakeRegistry(bodies={"main": b"tampered", "main-backup": b"still wrong"})
        hub = Molhub(
            index_dir,
            fetcher=Fetcher(drivers=Drivers.of(fake), blobs=BlobStore(root=tmp_path / "home")),
        )
        with pytest.raises(AllLocatorsFailed):
            hub.fetch("qm9@v2", roles=["main"])

    def test_wrong_bytes_are_not_stored(self, index_dir, tmp_path):
        home = tmp_path / "home"
        fake = FakeRegistry(bodies={"main": b"tampered", "main-backup": b"still wrong"})
        hub = Molhub(
            index_dir, fetcher=Fetcher(drivers=Drivers.of(fake), blobs=BlobStore(root=home))
        )
        with pytest.raises(AllLocatorsFailed):
            hub.fetch("qm9@v2", roles=["main"])
        assert [p for p in home.rglob("*") if p.is_file()] == []

    def test_falls_through_to_the_backup_locator(self, index_dir, tmp_path):
        fake = FakeRegistry(bodies={"main": b"tampered", "main-backup": MAIN_BODY})
        hub = Molhub(
            index_dir,
            fetcher=Fetcher(drivers=Drivers.of(fake), blobs=BlobStore(root=tmp_path / "home")),
        )
        assert hub.fetch("qm9@v2", roles=["main"])["main"].read_bytes() == MAIN_BODY


class TestSearch:
    def test_finds_by_query(self, hub):
        assert hub.search(query="qm9")

    def test_filters_by_kind(self, hub):
        assert hub.search(kind="model") == []

    def test_len_reports_the_index_size(self, hub):
        assert len(hub) == 1

    def test_repr_is_informative(self, hub):
        assert "1 artifacts" in repr(hub)


class TestExtensibility:
    def test_a_new_manifest_needs_no_source_change(self, index_dir, bodies, tmp_path):
        """The central claim of this layer: adding a dataset is data, not code."""
        import molhub

        source_root = __import__("pathlib").Path(molhub.__file__).parent
        before = {p: p.stat().st_mtime_ns for p in source_root.rglob("*.py")}

        added = index_dir / "dataset" / "someone-else" / "mydata" / "1.yaml"
        added.parent.mkdir(parents=True)
        added.write_text(
            (index_dir / "dataset" / "molcrafts" / "qm9" / "v2.yaml")
            .read_text()
            .replace("namespace: molcrafts", "namespace: someone-else")
            .replace("name: qm9", "name: mydata")
            .replace("version: v2", "version: 1")
        )

        fake = FakeRegistry(bodies=bodies)
        hub = Molhub(
            index_dir,
            fetcher=Fetcher(drivers=Drivers.of(fake), blobs=BlobStore(root=tmp_path / "home")),
        )
        assert hub.resolve("dataset:someone-else/mydata@1").coordinate.name == "mydata"
        assert hub.fetch("dataset:someone-else/mydata@1", roles=["main"])["main"].exists()

        after = {p: p.stat().st_mtime_ns for p in source_root.rglob("*.py")}
        assert before == after, "molhub source was modified while adding a dataset"
