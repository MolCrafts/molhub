"""Manifest — the record that says where an artifact's bytes actually are.

A manifest is data, not code. Adding a dataset to molhub is a YAML file in the
registry, not a Python module and not a release. That is the whole reason this
layer exists.

Parsing is typed and strict rather than schema-driven at runtime: the shipped
``schema/manifest.schema.yaml`` is the language-neutral contract for the registry
CI and for non-Python clients, while this module produces precise, actionable
errors without dragging a validator into every install.

A manifest names **one version** of an artifact, and the thing that makes that
precise is the **locator**, which must pin a version upstream understands:
a Zenodo record id, a Figshare article *plus* its version number, a HuggingFace
commit. Persistent identifiers do this job already — that is what they are for
— so a manifest records the ``doi`` and pins the locator, and does not need to
invent an identity of its own.

Getting this wrong is quiet. ``figshare://1057646`` resolves to whatever is
current, so a manifest written against v2 starts serving v3 the day upstream
publishes one, with nothing to indicate it.

``digest`` is optional and secondary: whatever the platform publishes for the
file, copied verbatim (Figshare and Zenodo publish md5, HuggingFace a sha256
LFS OID). It catches a platform breaking its own immutability promise. molhub
never invents one — a number computed from its own download attests only to
that download, and requiring it would mean fetching an entire artifact just to
write a registry entry.

``size`` is optional in the same way, but **not both at once**: an artifact
must record a ``digest``, a ``size``, or both, or a completed transfer has
nothing whatsoever to be checked against. Requiring one of the two keeps
cataloguing cheap — a size comes from a HEAD request's content-length, which
hauls no bytes — while requiring a digest outright would not.

Corrupt and truncated transfers are caught by the transport contract in
:mod:`molhub.sources` (status check, temp file, atomic rename), which depends
on none of this.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from molhub.coordinate import Coordinate, InvalidCoordinate
from molhub.sources import Digest, InvalidDigest, Locator

__all__ = ["Artifact", "TargetDeclaration", "Manifest", "InvalidManifest"]

SCHEMA_VERSION = 1
FORMAT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._+-]*$")
MEDIA_TYPE_PATTERN = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")


class InvalidManifest(ValueError):
    """A manifest is missing a required field or has one of the wrong shape."""


def _require(data: Mapping[str, Any], key: str, where: str) -> Any:
    try:
        value = data[key]
    except (KeyError, TypeError):
        raise InvalidManifest(f"{where} is missing required field {key!r}.") from None
    if value is None or value == "":
        raise InvalidManifest(f"{where} has an empty {key!r}.")
    return value


@dataclass(frozen=True)
class Artifact:
    """One downloadable file belonging to an artifact.

    At least one of ``digest`` and ``size`` is always present: either alone is
    a usable cross-check on a completed transfer, but neither leaves one
    unverifiable.

    Attributes:
        role: How the consumer refers to this file — ``main``, ``exclude``, …
        filename: Name to give the file locally.
        format: Stable identifier for the artifact's byte format. Consumers
            use this instead of inferring a format from the filename.
        media_type: Optional IANA-style media type without parameters.
        locators: Ordered candidate sources; earlier ones are preferred.
        digest: What the platform publishes for this file, copied verbatim, or
            ``None`` when it publishes nothing. Used to confirm upstream still
            serves the version this manifest names.
        size: Byte count, from what the platform reports or a HEAD request.
            ``None`` only when a ``digest`` is present to check against.
    """

    role: str
    filename: str
    locators: tuple[Locator, ...]
    format: str | None = None
    media_type: str | None = None
    digest: Digest | None = None
    size: int | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, where: str) -> "Artifact":
        """Build an artifact from one entry of a manifest's ``artifacts`` list.

        Raises:
            InvalidManifest: If a required field is missing or malformed.
        """
        role = str(_require(data, "role", where))
        scope = f"{where} artifact {role!r}"

        raw_digest = data.get("digest")
        try:
            digest = Digest.parse(str(raw_digest)) if raw_digest else None
        except InvalidDigest as error:
            raise InvalidManifest(f"{scope} has an unusable digest: {error}") from error

        raw_locators = _require(data, "locators", scope)
        if isinstance(raw_locators, str) or not isinstance(raw_locators, Sequence):
            raise InvalidManifest(f"{scope} expects 'locators' to be a list.")
        if not raw_locators:
            raise InvalidManifest(f"{scope} lists no locators.")
        locators = tuple(Locator.parse(str(entry)) for entry in raw_locators)

        raw_size = data.get("size")
        size = int(raw_size) if raw_size is not None else None
        if size is not None and size <= 0:
            raise InvalidManifest(
                f"{scope} declares size {size}, but zero is not a smaller artifact — "
                f"it is the shape of a failed transfer. Since a size may be the only "
                f"cross-check an artifact carries, accepting it would let an empty "
                f"download verify as correct, which is the failure this registry "
                f"exists to prevent."
            )
        if digest is None and size is None:
            raise InvalidManifest(
                f"{scope} records neither a digest nor a size, leaving nothing to "
                f"check a completed transfer against. Copy whatever checksum the "
                f"platform publishes; when it publishes none, a 'size' is an "
                f"acceptable answer and a HEAD request's content-length will give "
                f"you one without downloading the file. Never compute a digest "
                f"yourself — it would only attest to your own download."
            )

        artifact_format = str(data["format"]) if data.get("format") else None
        if artifact_format is not None and not FORMAT_PATTERN.fullmatch(artifact_format):
            raise InvalidManifest(
                f"{scope} has invalid format {artifact_format!r}; use a stable lowercase "
                "identifier such as 'extxyz' instead of a display label."
            )
        media_type = str(data["media_type"]) if data.get("media_type") else None
        if media_type is not None and not MEDIA_TYPE_PATTERN.fullmatch(media_type):
            raise InvalidManifest(
                f"{scope} has invalid media_type {media_type!r}; use a type/subtype "
                "without response parameters."
            )

        return cls(
            role=role,
            filename=str(_require(data, "filename", scope)),
            locators=locators,
            format=artifact_format,
            media_type=media_type,
            digest=digest,
            size=size,
        )


@dataclass(frozen=True)
class TargetDeclaration:
    """Which targets an artifact carries, and at which level.

    Declarative metadata for display and for downstream consumers to act on.
    Nothing in this chain parses bytes according to it.
    """

    graph_level: tuple[str, ...] = field(default_factory=tuple)
    atom_level: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "TargetDeclaration":
        """Build from a manifest's ``targets`` block; an absent block is empty."""
        if not data:
            return cls()
        return cls(
            graph_level=tuple(str(name) for name in data.get("graph_level") or ()),
            atom_level=tuple(str(name) for name in data.get("atom_level") or ()),
        )


@dataclass(frozen=True)
class Manifest:
    """Everything the registry knows about one version of one artifact."""

    coordinate: Coordinate
    title: str
    artifacts: Mapping[str, Artifact]
    description: str = ""
    license: str | None = None
    doi: str | None = None
    """The persistent identifier for exactly this version, when upstream mints
    one. Zenodo gives a per-version DOI alongside a concept DOI for "latest";
    Figshare gives one per article. It is both the citation and the assurance
    that the pinned locator means what the manifest says."""
    targets: TargetDeclaration = field(default_factory=TargetDeclaration)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, where: str = "manifest") -> "Manifest":
        """Build a manifest from an already-parsed mapping.

        Raises:
            InvalidManifest: If a required field is missing, the schema version
                is unknown, or any artifact is malformed.
        """
        if not isinstance(data, Mapping):
            raise InvalidManifest(f"{where} must be a mapping, got {type(data).__name__}.")

        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise InvalidManifest(
                f"{where} declares schema_version {version!r}; this molhub "
                f"understands {SCHEMA_VERSION}."
            )

        try:
            coordinate = Coordinate(
                kind=str(_require(data, "kind", where)),
                namespace=str(_require(data, "namespace", where)),
                name=str(_require(data, "name", where)),
                version=str(_require(data, "version", where)),
            )
        except InvalidCoordinate as error:
            # Surface where the bad coordinate lives; the caller is loading a
            # file, not parsing a coordinate they typed.
            raise InvalidManifest(f"{where} has an invalid coordinate: {error}") from error
        scope = f"{where} {coordinate.canonical}"

        raw_artifacts = _require(data, "artifacts", scope)
        if isinstance(raw_artifacts, Mapping) or not isinstance(raw_artifacts, Sequence):
            raise InvalidManifest(f"{scope} expects 'artifacts' to be a list.")

        artifacts: dict[str, Artifact] = {}
        for entry in raw_artifacts:
            artifact = Artifact.from_mapping(entry, where=scope)
            if artifact.role in artifacts:
                raise InvalidManifest(f"{scope} declares role {artifact.role!r} twice.")
            artifacts[artifact.role] = artifact
        if not artifacts:
            raise InvalidManifest(f"{scope} lists no artifacts.")

        return cls(
            coordinate=coordinate,
            title=str(_require(data, "title", scope)),
            artifacts=artifacts,
            description=str(data.get("description") or ""),
            license=str(data["license"]) if data.get("license") else None,
            doi=str(data["doi"]) if data.get("doi") else None,
            targets=TargetDeclaration.from_mapping(data.get("targets")),
        )

    @classmethod
    def from_yaml(cls, text: str, *, where: str = "manifest") -> "Manifest":
        """Parse a manifest from YAML source.

        Comments are ordinary YAML and do not reach the parsed result — a
        manifest is meant to be read and reviewed by people, so explaining a
        mirror choice inline should cost nothing.

        Raises:
            InvalidManifest: If the YAML is malformed or the content invalid.
        """
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise InvalidManifest(f"{where} is not valid YAML: {error}") from error
        return cls.from_mapping(data, where=where)

    @classmethod
    def from_path(cls, path: Path) -> "Manifest":
        """Parse the manifest stored at *path*."""
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"), where=str(path))

    def artifact(self, role: str) -> Artifact:
        """Return the artifact filed under *role*.

        Raises:
            KeyError: If this manifest declares no such role.
        """
        try:
            return self.artifacts[role]
        except KeyError:
            available = ", ".join(sorted(self.artifacts))
            raise KeyError(
                f"{self.coordinate.canonical} has no artifact role {role!r}. Available: {available}"
            ) from None

    def matches(self, query: str) -> bool:
        """Whether *query* occurs in the fields a person would search on."""
        needle = query.casefold()
        haystack = " ".join(
            [
                self.coordinate.canonical,
                self.title,
                self.description,
                self.doi or "",
                *self.targets.graph_level,
            ]
        ).casefold()
        return needle in haystack
