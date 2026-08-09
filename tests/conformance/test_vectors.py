"""Run the language-neutral MolHub contract against the Python client."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from molhub.coordinate import Coordinate, InvalidCoordinate
from molhub.manifest import InvalidManifest, Manifest
from molhub.registry import Registry
from molhub.sources import (
    AllLocatorsFailed,
    BadStatus,
    BlobStore,
    Digest,
    Drivers,
    Fetcher,
    InvalidDigest,
    Locator,
    RemoteFile,
)

VECTOR_ROOT = Path(__file__).parents[2] / "spec" / "conformance" / "vectors"


def _document(name: str) -> dict[str, Any]:
    return yaml.safe_load((VECTOR_ROOT / name).read_text(encoding="utf-8"))


def _cases(name: str) -> list[pytest.param]:
    return [pytest.param(case, id=case["name"]) for case in _document(name)["cases"]]


@pytest.mark.parametrize("case", _cases("coordinate.yaml"))
def test_coordinate_vectors(case: dict[str, Any]) -> None:
    expected = case["expect"]
    if expected.get("error"):
        assert expected["error"] == "invalid_coordinate"
        with pytest.raises(InvalidCoordinate):
            Coordinate.parse(case["input"])
        return

    coordinate = Coordinate.parse(case["input"])
    assert {
        "kind": coordinate.kind,
        "namespace": coordinate.namespace,
        "name": coordinate.name,
        "version": coordinate.version,
        "canonical": coordinate.canonical,
        "manifest_path": coordinate.relative_path(),
        "cache_path": coordinate.cache_path(),
    } == expected


@pytest.mark.parametrize("case", _cases("digest.yaml"))
def test_digest_vectors(case: dict[str, Any], tmp_path: Path) -> None:
    expected = case["expect"]
    if expected.get("error"):
        assert expected["error"] == "invalid_digest"
        with pytest.raises(InvalidDigest):
            Digest.parse(case["input"])
        return

    if "body_utf8" in case:
        sample = tmp_path / "sample"
        sample.write_bytes(case["body_utf8"].encode())
        actual = Digest.of_file(sample, algorithm=case["algorithm"])
    else:
        actual = Digest.parse(case["input"])
    assert str(actual) == expected["canonical"]


@pytest.mark.parametrize("case", _cases("cache_layout.yaml"))
def test_cache_layout_vectors(case: dict[str, Any], tmp_path: Path) -> None:
    relative = BlobStore(tmp_path).path_for(case["key"]).relative_to(tmp_path).as_posix()
    assert relative == case["expect_path"]


@pytest.mark.parametrize("case", _cases("manifest.yaml"))
def test_manifest_vectors(case: dict[str, Any]) -> None:
    expected = case["expect"]
    if expected.get("error"):
        error = expected["error"]
        assert error in {"invalid_manifest", "duplicate_role"}
        with pytest.raises(InvalidManifest):
            Manifest.from_mapping(case["document"])
        return
    manifest = Manifest.from_mapping(case["document"])
    assert manifest.coordinate.canonical == "dataset:molcrafts/example@v1"


@pytest.mark.parametrize("case", _cases("registry.yaml"))
def test_registry_vectors(case: dict[str, Any]) -> None:
    source = _document("registry.yaml")
    manifests = {
        entry["coordinate"]: Manifest.from_mapping(
            {key: value for key, value in entry.items() if key != "coordinate"}
            | {"schema_version": 1}
        )
        for entry in source["registry"]["entries"]
    }
    registry = Registry(manifests)
    if case["action"] == "resolve":
        assert registry.get(case["coordinate"]).coordinate.canonical == case["expect"]["coordinate"]
    else:
        result = registry.search(kind=case.get("kind"), query=case.get("query"))
        coordinates = [manifest.coordinate.canonical for manifest in result]
        assert coordinates == case["expect"]["coordinates"]


class _VectorSource:
    scheme = "mock"

    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses
        self.calls = 0

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        return [RemoteFile(url=str(locator), filename=locator.path)]

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        self.calls += 1
        response = self.responses[remote.url]
        if response["status"] != 200:
            raise BadStatus(f"{remote.url} returned HTTP {response['status']}.")
        dest.write_bytes(response["body_utf8"].encode())
        return dest


@pytest.mark.parametrize("case", _cases("fallback.yaml"))
def test_fallback_vectors(case: dict[str, Any], tmp_path: Path) -> None:
    source = _VectorSource(case["responses"])
    store = BlobStore(tmp_path)
    key = "dataset/molcrafts/example@v1/main"
    if cached := case.get("cached_body_utf8"):
        cached_path = store.path_for(key)
        cached_path.parent.mkdir(parents=True)
        cached_path.write_text(cached, encoding="utf-8")

    fetcher = Fetcher(drivers=Drivers.of(source), blobs=store)
    expected = case["expect"]
    if expected.get("error"):
        assert expected["error"] == "all_locators_failed"
        with pytest.raises(AllLocatorsFailed):
            fetcher.fetch(case["locators"], key, digest=case.get("digest"))
    else:
        result = fetcher.fetch(case["locators"], key, digest=case.get("digest"))
        assert result.read_text(encoding="utf-8") == expected["body_utf8"]

    assert source.calls == expected["network_calls"]
    files = [path for path in (tmp_path / "files").rglob("*") if path.is_file()]
    assert len(files) == expected["files_written"]


def test_every_vector_case_is_collected() -> None:
    expected = sum(len(_document(path.name)["cases"]) for path in VECTOR_ROOT.glob("*.yaml"))
    collected = sum(
        len(_cases(name))
        for name in (
            "coordinate.yaml",
            "digest.yaml",
            "cache_layout.yaml",
            "manifest.yaml",
            "registry.yaml",
            "fallback.yaml",
        )
    )
    assert collected == expected


def test_runner_rejects_an_intentionally_wrong_expectation() -> None:
    coordinate = Coordinate.parse("qm9@v2")
    with pytest.raises(AssertionError):
        assert coordinate.canonical == "dataset:molcrafts/qm9@wrong"
