"""Regression for immutable publish -> resolve -> fetch driver closures.

Hard-coded golden provenance: molhub-delivery-01-close-publish contract,
version 1, command ``uv run python regressions/molhub-delivery-01-close-publish.py``,
captured 2026-08-09. No third-party service is contacted.
"""

from __future__ import annotations

import json
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from molhub.sources.drivers.figshare import FigshareSource
from molhub.sources.drivers.huggingface import HuggingFaceSource
from molhub.sources.publication import Publication
from molhub.sources.remote import RemoteFile

_CONTENT = b"a,b\n1,2\n"
_HF_OID = "0123456789abcdef0123456789abcdef01234567"


class FakeResponse:
    """Minimal response used by both the fake session and ``urlopen``."""

    status = 200
    status_code = 200

    def __init__(
        self,
        payload: Any,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.headers = {} if headers is None else headers

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._payload

    def read(self, _size: int = -1) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        pass


class FakeFigshareSession:
    """Deterministic authenticated Figshare account API."""

    upload_url = "https://uploads.invalid/7"

    def post(self, url: str, *, json: Any = None) -> FakeResponse:
        if url.endswith("/account/articles"):
            return FakeResponse({"id": 99})
        if url.endswith("/account/articles/99/files"):
            return FakeResponse({"id": 7, "name": "data.csv", "upload_url": self.upload_url})
        if url.endswith("/account/articles/99/files/7"):
            return FakeResponse({"id": 7, "name": "data.csv"})
        if url.endswith("/account/articles/99/publish"):
            return FakeResponse({"id": 99, "version": 3})
        if url == self.upload_url:
            return FakeResponse({"parts": []})
        raise AssertionError(f"Unexpected Figshare POST {url} with {json!r}")

    def get(self, url: str) -> FakeResponse:
        if url == self.upload_url:
            return FakeResponse({"parts": []})
        if url.endswith("/account/articles/99"):
            return FakeResponse({"id": 99, "version": 3})
        raise AssertionError(f"Unexpected Figshare GET {url}")

    def put(self, url: str, *, data: bytes) -> FakeResponse:
        assert url == self.upload_url
        assert data == _CONTENT
        return FakeResponse({})


class FakeTransfer:
    """Plain byte transfer injected through the drivers' public constructor."""

    def __init__(self, expected_url: str) -> None:
        self._expected_url = expected_url

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        assert remote.url == self._expected_url
        dest.write_bytes(_CONTENT)
        return dest


@dataclass(frozen=True)
class FakeCommitInfo:
    oid: str


class FakeHuggingFaceSource(HuggingFaceSource):
    """Hugging Face driver with deterministic public upload primitives."""

    def create_repo(
        self,
        repo_id: str,
        *,
        private: bool = False,
        exist_ok: bool = True,
    ) -> str:
        assert (repo_id, private, exist_ok) == ("org/ds", False, True)
        return "https://huggingface.invalid/datasets/org/ds"

    def upload_file(
        self,
        local_path: str | Path,
        repo_id: str,
        path_in_repo: str,
        *,
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> FakeCommitInfo:
        assert Path(local_path).read_bytes() == _CONTENT
        assert (repo_id, path_in_repo) == ("org/ds", "data.csv")
        assert commit_message is None
        assert kwargs == {}
        return FakeCommitInfo(oid=_HF_OID)


def main() -> None:
    publication = Publication(title="Pinned publication")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source_file = root / "data.csv"
        source_file.write_bytes(_CONTENT)

        figshare_url = "https://downloads.invalid/data.csv"
        figshare = FigshareSource(
            api_base="https://api.invalid",
            token="fake-token",
            transfer=FakeTransfer(figshare_url),
        )
        figshare._session_cache = FakeFigshareSession()

        original_urlopen = urllib.request.urlopen

        def fake_urlopen(request: urllib.request.Request) -> FakeResponse:
            assert request.full_url == "https://api.invalid/articles/99/versions/3"
            return FakeResponse(
                {
                    "files": [
                        {
                            "name": "data.csv",
                            "size": len(_CONTENT),
                            "download_url": figshare_url,
                        }
                    ]
                }
            )

        urllib.request.urlopen = fake_urlopen
        try:
            figshare_locator = figshare.publish([source_file], "new", publication)
            assert str(figshare_locator) == "figshare://99/v3/data.csv"
            figshare_remote = figshare.resolve(figshare_locator)[0]
            figshare_dest = figshare.fetch(figshare_remote, root / "figshare.csv")
            assert figshare_dest.read_bytes() == _CONTENT
        finally:
            urllib.request.urlopen = original_urlopen

        hf_url = f"https://huggingface.invalid/datasets/org/ds/resolve/{_HF_OID}/data.csv"
        huggingface = FakeHuggingFaceSource(
            endpoint="https://huggingface.invalid",
            token="fake-token",
            transfer=FakeTransfer(hf_url),
        )
        hf_locator = huggingface.publish([source_file], "org/ds", publication)
        assert str(hf_locator) == f"hf://org/ds@{_HF_OID}/data.csv"
        hf_remote = huggingface.resolve(hf_locator)[0]
        hf_dest = huggingface.fetch(hf_remote, root / "huggingface.csv")
        assert hf_dest.read_bytes() == _CONTENT


if __name__ == "__main__":
    main()
