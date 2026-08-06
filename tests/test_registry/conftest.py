"""Shared fakes for registry tests — no test here touches the network."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from molhub.registry.errors import BadStatus
from molhub.registry.locator import Locator
from molhub.registry.remote import RemoteFile


class FakeResponse(io.BytesIO):
    """Minimal stand-in for the object ``urlopen`` yields."""

    def __init__(self, status: int = 200, body: bytes = b"") -> None:
        super().__init__(body)
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        self.close()
        return False


@dataclass
class FakeRegistry:
    """A Registry driver that serves canned bytes and counts its calls.

    ``scheme`` is settable so a test can register several independent fakes.
    ``bodies`` maps a locator path to the bytes served for it; a path mapped to
    an ``int`` is served as that HTTP status with an empty body.
    """

    scheme: str = "fake"
    bodies: dict[str, bytes | int] = field(default_factory=dict)
    upstream_digest: str | None = None
    resolve_calls: list[Locator] = field(default_factory=list)
    fetch_calls: list[str] = field(default_factory=list)

    @property
    def network_calls(self) -> int:
        return len(self.fetch_calls)

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        self.resolve_calls.append(locator)
        return [
            RemoteFile(
                url=f"{self.scheme}://{locator.path}",
                filename=locator.path,
                upstream_digest=self.upstream_digest,
            )
        ]

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        self.fetch_calls.append(remote.url)
        key = remote.url.split("://", 1)[1]
        body = self.bodies.get(key, b"")
        if isinstance(body, int):
            raise BadStatus(f"{remote.url} returned HTTP {body}, expected 200")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        return dest


@pytest.fixture
def molhub_home(tmp_path, monkeypatch):
    """Point $MOLHUB_HOME at an empty temporary directory."""
    home = tmp_path / "molhub-home"
    monkeypatch.setenv("MOLHUB_HOME", str(home))
    return home
