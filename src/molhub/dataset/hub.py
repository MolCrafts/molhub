"""What a dataset source requires of the layer beneath it.

A source's entire dependency on molhub is one verb: hand over a coordinate,
get local paths back. Naming :class:`~molhub.molhub.Molhub` at that seam would
say something stronger and untrue — that reading a file needs a registry, a
driver table and a search API — and it would make every stand-in a subclass
problem rather than a shape problem.

This is the required side of the boundary; :mod:`molhub.dataset.protocol`
describes the exposed side, the interfaces a dataset offers its consumers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = ["ArtifactHub"]


@runtime_checkable
class ArtifactHub(Protocol):
    """A source of artifact files, addressed by coordinate.

    :class:`~molhub.molhub.Molhub` satisfies this by shape and declares
    nothing; so does any substitute a caller injects — a fake serving files
    already on disk, an offline mirror, a hub bound to a private registry.
    """

    def fetch(self, coordinate: str, *, roles: list[str] | None = None) -> dict[str, Path]:
        """Return the artifact's files, keyed by role.

        Args:
            coordinate: The artifact to retrieve.
            roles: Restrict to these roles; ``None`` retrieves every one.

        Returns:
            Mapping of role to the local path holding that file's bytes.

        Raises:
            KeyError: If a requested role is not one the artifact declares.
        """
        ...
