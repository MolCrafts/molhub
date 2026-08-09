"""Tests for the HuggingFace source driver."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

import pytest

from molhub.sources.drivers.huggingface import HuggingFaceSource
from molhub.sources.errors import InvalidLocator, SourceError
from molhub.sources.locator import Locator
from molhub.sources.publication import Publication
from molhub.sources.remote import RemoteFile

_OID_40 = "0123456789abcdef0123456789abcdef01234567"
_OID_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_PAYLOAD = b"a,b\n1,2\n"


@dataclass(frozen=True)
class _CommitInfo:
    oid: str | None
    url: str = "https://huggingface.co/datasets/org/ds/blob/main/data.csv"


class _MissingCommitInfo:
    url = "https://huggingface.co/datasets/org/ds/blob/main/data.csv"


class _FakeTransfer:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.calls: list[tuple[RemoteFile, Path]] = []

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        self.calls.append((remote, dest))
        dest.write_bytes(self._payload)
        return dest


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    path = tmp_path / "data.csv"
    path.write_bytes(_PAYLOAD)
    return path


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> mock.MagicMock:
    fake = mock.MagicMock()
    fake.create_repo.return_value = "https://huggingface.co/datasets/org/ds"
    fake.upload_file.return_value = _CommitInfo(oid=_OID_40)
    fake.upload_folder.return_value = _CommitInfo(oid=_OID_40)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    return fake


class TestHuggingFaceSource:
    def test_default_revision_is_main(self):
        remote = HuggingFaceSource().resolve(Locator.parse("hf://MolCrafts/qm9/qm9.tar.bz2"))[0]
        assert remote.url == (
            "https://huggingface.co/datasets/MolCrafts/qm9/resolve/main/qm9.tar.bz2"
        )

    def test_pinned_revision(self):
        remote = HuggingFaceSource().resolve(
            Locator.parse("hf://MolCrafts/qm9@abc1234/qm9.tar.bz2")
        )[0]
        assert "/resolve/abc1234/" in remote.url

    def test_nested_file_path_is_preserved(self):
        remote = HuggingFaceSource().resolve(Locator.parse("hf://org/repo/raw/inner/f.bin"))[0]
        assert remote.url.endswith("/resolve/main/raw/inner/f.bin")

    def test_filename_is_the_last_segment(self):
        remote = HuggingFaceSource().resolve(Locator.parse("hf://org/repo/raw/inner/f.bin"))[0]
        assert remote.filename == "f.bin"

    def test_mirror_endpoint_needs_no_manifest_change(self):
        """Pointing at hf-mirror.com is a client-side setting, not a new locator."""
        source = HuggingFaceSource(endpoint="https://hf-mirror.com")
        remote = source.resolve(Locator.parse("hf://MolCrafts/qm9/qm9.tar.bz2"))[0]
        assert remote.url.startswith("https://hf-mirror.com/datasets/")

    def test_models_repo_type_drops_the_prefix(self):
        source = HuggingFaceSource(repo_type="models")
        remote = source.resolve(Locator.parse("hf://org/mace-mp-0/weights.pt"))[0]
        assert remote.url == "https://huggingface.co/org/mace-mp-0/resolve/main/weights.pt"

    @pytest.mark.parametrize("path", ["org", "org/repo"])
    def test_too_short_path_raises(self, path):
        with pytest.raises(InvalidLocator):
            HuggingFaceSource().resolve(Locator.parse(f"hf://{path}"))

    def test_unknown_repo_type_raises(self):
        with pytest.raises(ValueError, match="repo_type"):
            HuggingFaceSource(repo_type="notebooks")

    def test_scheme(self):
        assert HuggingFaceSource().scheme == "hf"

    @pytest.mark.parametrize("case", ["empty", "two-files", "directory"])
    def test_publish_rejects_non_single_regular_file_before_network(
        self,
        case: str,
        hub: mock.MagicMock,
        payload: Path,
        tmp_path: Path,
    ) -> None:
        other = tmp_path / "other.csv"
        other.write_bytes(b"other")
        directory = tmp_path / "bundle"
        directory.mkdir()
        paths = {
            "empty": [],
            "two-files": [payload, other],
            "directory": [directory],
        }[case]

        with pytest.raises(SourceError):
            HuggingFaceSource(token="t").publish(
                paths,
                "org/ds",
                Publication(title="Dataset"),
            )

        hub.create_repo.assert_not_called()
        hub.upload_file.assert_not_called()
        hub.upload_folder.assert_not_called()

    def test_publish_rejects_missing_file_before_network(
        self,
        hub: mock.MagicMock,
        tmp_path: Path,
    ) -> None:
        with pytest.raises(FileNotFoundError):
            HuggingFaceSource(token="t").publish(
                [tmp_path / "missing.csv"],
                "org/ds",
                Publication(title="Dataset"),
            )

        hub.create_repo.assert_not_called()
        hub.upload_file.assert_not_called()
        hub.upload_folder.assert_not_called()

    def test_publish_rejects_private_publication_before_network(
        self,
        hub: mock.MagicMock,
        payload: Path,
    ) -> None:
        with pytest.raises(SourceError, match="public|private"):
            HuggingFaceSource(token="t").publish(
                [payload],
                "org/ds",
                Publication(title="Dataset", private=True),
            )

        hub.create_repo.assert_not_called()
        hub.upload_file.assert_not_called()
        hub.upload_folder.assert_not_called()

    @pytest.mark.parametrize(
        ("oid", "expected_oid"),
        [
            (_OID_40.upper(), _OID_40),
            (_OID_64.upper(), _OID_64),
        ],
    )
    def test_publish_returns_exact_locator_from_complete_commit_oid(
        self,
        oid: str,
        expected_oid: str,
        hub: mock.MagicMock,
        payload: Path,
    ) -> None:
        hub.upload_file.return_value = _CommitInfo(oid=oid)

        locator = HuggingFaceSource(token="t").publish(
            [payload],
            "org/ds",
            Publication(title="Dataset"),
        )

        assert locator == Locator.parse(f"hf://org/ds@{expected_oid}/data.csv")

    def test_publish_creates_repository_before_upload(
        self,
        hub: mock.MagicMock,
        payload: Path,
    ) -> None:
        calls: list[str] = []

        def record_create(**kwargs):
            calls.append("create")
            return "https://huggingface.co/datasets/org/ds"

        def record_upload(**kwargs):
            calls.append("upload")
            return _CommitInfo(oid=_OID_40)

        hub.create_repo.side_effect = record_create
        hub.upload_file.side_effect = record_upload

        HuggingFaceSource(token="t").publish(
            [payload],
            "org/ds",
            Publication(title="Dataset"),
        )

        assert calls == ["create", "upload"]
        assert hub.create_repo.call_args.kwargs["repo_id"] == "org/ds"

    @pytest.mark.parametrize(
        ("repo_type", "hub_repo_type", "target"),
        [
            ("datasets", "dataset", "org/ds"),
            ("models", "model", "org/model"),
        ],
    )
    def test_publish_maps_repo_type_for_hub_api(
        self,
        repo_type: str,
        hub_repo_type: str,
        target: str,
        hub: mock.MagicMock,
        payload: Path,
    ) -> None:
        HuggingFaceSource(token="t", repo_type=repo_type).publish(
            [payload],
            target,
            Publication(title="Dataset"),
        )

        assert hub.create_repo.call_args.kwargs["repo_type"] == hub_repo_type

    @pytest.mark.parametrize(
        "upload_result",
        [
            pytest.param(_MissingCommitInfo(), id="missing"),
            pytest.param(_CommitInfo(oid=None), id="none"),
            pytest.param(_CommitInfo(oid="abc1234"), id="abbreviated"),
            pytest.param(_CommitInfo(oid="a" * 39), id="39-characters"),
            pytest.param(_CommitInfo(oid="a" * 41), id="41-characters"),
            pytest.param(_CommitInfo(oid="a" * 63), id="63-characters"),
            pytest.param(_CommitInfo(oid="a" * 65), id="65-characters"),
            pytest.param(_CommitInfo(oid="g" * 40), id="non-hexadecimal"),
        ],
    )
    def test_publish_rejects_missing_or_non_immutable_commit_oid(
        self,
        upload_result: object,
        hub: mock.MagicMock,
        payload: Path,
    ) -> None:
        hub.upload_file.return_value = upload_result

        with pytest.raises(SourceError, match="OID|oid"):
            HuggingFaceSource(token="t").publish(
                [payload],
                "org/ds",
                Publication(title="Dataset"),
            )

    def test_publish_reads_oid_instead_of_upload_url(
        self,
        hub: mock.MagicMock,
        payload: Path,
    ) -> None:
        hub.upload_file.return_value = _CommitInfo(
            oid=_OID_40,
            url=(f"https://huggingface.co/datasets/org/ds/blob/{'f' * 64}/data.csv"),
        )

        locator = HuggingFaceSource(token="t").publish(
            [payload],
            "org/ds",
            Publication(title="Dataset"),
        )

        assert locator == Locator.parse(f"hf://org/ds@{_OID_40}/data.csv")

    def test_upload_file_returns_hub_result_unchanged(
        self,
        hub: mock.MagicMock,
        payload: Path,
    ) -> None:
        result = _CommitInfo(oid=_OID_64)
        hub.upload_file.return_value = result

        uploaded = HuggingFaceSource(token="t").upload_file(
            payload,
            "org/ds",
            path_in_repo="data.csv",
        )

        assert uploaded is result

    def test_upload_folder_returns_hub_result_unchanged(
        self,
        hub: mock.MagicMock,
        tmp_path: Path,
    ) -> None:
        folder = tmp_path / "bundle"
        folder.mkdir()
        result = _CommitInfo(oid=_OID_64)
        hub.upload_folder.return_value = result

        uploaded = HuggingFaceSource(token="t").upload_folder(
            folder,
            "org/ds",
            path_in_repo="bundle",
        )

        assert uploaded is result

    def test_publish_resolve_fetch_closes_public_file_loop(
        self,
        hub: mock.MagicMock,
        payload: Path,
        tmp_path: Path,
    ) -> None:
        hub.upload_file.return_value = _CommitInfo(oid=_OID_40)
        transfer = _FakeTransfer(_PAYLOAD)
        source = HuggingFaceSource(token="t", transfer=transfer)

        locator = source.publish(
            [payload],
            "org/ds",
            Publication(title="Dataset"),
        )
        remote = source.resolve(locator)[0]
        fetched = source.fetch(remote, tmp_path / "fetched.csv")

        assert locator == Locator.parse(f"hf://org/ds@{_OID_40}/data.csv")
        assert remote.url == (f"https://huggingface.co/datasets/org/ds/resolve/{_OID_40}/data.csv")
        assert transfer.calls == [(remote, tmp_path / "fetched.csv")]
        assert fetched.read_bytes() == _PAYLOAD
