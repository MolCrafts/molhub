"""Tests for the ArtifactHub seam.

Nothing here constructs a :class:`~molhub.molhub.Molhub`: the point of the
protocol is that the facade fits it by shape, which is a question about the
class, not about a running instance with a registry behind it.
"""

from __future__ import annotations

from pathlib import Path

from molhub.dataset import ArtifactHub
from molhub.molhub import Molhub


def _the_facade_fits_the_seam(hub: Molhub) -> ArtifactHub:
    """Static proof, checked by ``ty``, that :class:`Molhub` satisfies the seam.

    Never called. If :meth:`Molhub.fetch` ever narrows its parameters or
    widens its return type, this line stops type-checking — which is the whole
    point of writing it down.
    """
    return hub


class _MinimalHub:
    """The least a stand-in can be: one method, no molhub types."""

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        return {}


class _NoFetch:
    def resolve(self, coordinate: str) -> None: ...


class TestArtifactHub:
    def test_molhub_satisfies_it_without_declaring_it(self):
        """The facade names no protocol; it fits by shape alone."""
        assert issubclass(Molhub, ArtifactHub)

    def test_a_one_method_stand_in_satisfies_it(self):
        """A fake needs no registry, no driver table, and no search API."""
        assert isinstance(_MinimalHub(), ArtifactHub)

    def test_something_without_fetch_does_not_satisfy_it(self):
        assert not isinstance(_NoFetch(), ArtifactHub)

    def test_the_seam_is_exactly_one_verb(self):
        """Widening this would rebuild the facade the protocol replaces."""
        assert [name for name in vars(ArtifactHub) if not name.startswith("_")] == ["fetch"]
