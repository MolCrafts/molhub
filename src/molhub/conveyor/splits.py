"""The split assignment of record, trusted only once its own producer agrees.

``class1-universal-splits@1`` is the one answer to *which split does this
molecule belong to*, and every consumer downstream of it — the roster's
provenance stamp, the prepare stage's routing — has to be able to say which
version of that answer it used. So the split tables are never read bare: each
one is checked against the ``output_sha256`` block that
``molhub.scripts.build_class1_splits`` wrote beside it, and a table that no
longer matches its own record is refused rather than silently routing molecules
into the wrong split for the rest of a training run.

**A refusal names the module, not the recorded field.** Every derivation already
on disk records ``scripts/build_class1_splits.py`` in its own ``metadata.json``,
which is now a shim that never shipped in the wheel; echoing that field would
tell a pip-installed reader to run a file they do not have. The messages here
state ``python -m molhub.scripts.build_class1_splits`` and quote the recorded
generator beside it, so the provenance is still visible and the instruction is
still runnable.

**Hashing a local file here is not molhub inventing a digest.** The repo rule
(``.claude/notes/notes.md``) forbids computing a digest for an *upstream*
artifact in order to catalogue it: such a number attests only to whichever
download produced it, and demanding one would mean hauling the artifact before
it could be listed. Checking a **completed local file against a digest its own
producer recorded** is the already-legitimate other case, and the transport
layer has always done exactly that — ``Fetcher._fetch_one``
(``src/molhub/sources/fetcher.py:108``) hashes the file it just wrote and
compares it with the manifest's value. This module does the same thing one
layer up, through the same :meth:`~molhub.sources.digest.Digest.of_file` /
:meth:`~molhub.sources.digest.Digest.matches` pair, and owns no hashing code.

**Filenames are a literal table, never a glob.** The producer's own ``out_name``
map is irregular — ``torsion-scan`` writes ``torsion_scan_splits.csv.gz``, with
no ``_uuid_`` — and a directory glob would paper over precisely that
irregularity while also sweeping in ``identity_splits.csv.gz``, which is keyed
by molecule identity rather than by scan uuid. An unknown source is a
:class:`KeyError` naming the sources this derivation publishes.

**One source per instance, two key spaces, one implementation.** The full set is
millions of rows and a caller only ever needs one table, so
:meth:`_SplitTable.from_derived` loads exactly one uuid-keyed source and
:meth:`_SplitTable.from_identity` loads the identity-keyed table. They are two
alternate constructors over one loader and one provenance check — not two
loaders — and each instance is honest about which key space it holds: asking an
identity table for a uuid raises rather than answering ``None``.

**The table is package-internal.** It was exported while ``-02-roster`` was its
only caller and had no other way to hand one over. ``hf-facade-03-builder-info``
(D9) added the second caller — :class:`~molhub.loader.builder.DatasetBuilder`
counts a table-backed split with it — and both live inside this distribution, so
the name lost its ``molhub.conveyor`` export rather than growing a public
duplicate beside it. Provenance verification, the literal filename table and the
two alternate constructors are exactly as they were; only the export went.

Reference:
    ``.claude/specs/streaming-data-tiers-03-conveyor-02-roster.md``
    § *``SplitTable`` — the split assignment of record, with its provenance*;
    ``.claude/specs/hf-facade-03-builder-info.md`` § D9, under the 2026-08-15
    operator override in ``.claude/notes/notes.md``.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from molhub.conveyor.block import ConveyorError
from molhub.sources.digest import Digest
from molhub.sources.errors import InvalidDigest

__all__ = ["SplitProvenance", "SplitProvenanceMismatch"]

_METADATA_FILENAME = "metadata.json"

# The generator that rewrites a derivation, as a command a reader can type.
# Every table already on disk records the *legacy* `scripts/build_class1_splits.py`
# path in its own `metadata.json`, and that file is a shim which never shipped in
# the wheel — so echoing the recorded field would name something a pip-installed
# reader does not have. The module is stated here instead, mirrored from
# `molhub.scripts.build_class1_splits` rather than imported for the reason the
# filename table above is mirrored: it is a script, run once per derivation, and
# importing it would drag its argument parsing into every reader.
_GENERATOR_MODULE = "molhub.scripts.build_class1_splits"
_GENERATOR_COMMAND = f"python -m {_GENERATOR_MODULE}"

# The literal table from `molhub.scripts.build_class1_splits`'s own filename block.
# Mirrored rather than imported: that file is a script, run once per derivation,
# and importing it would drag its argument parsing into every reader.
_SOURCE_FILENAMES: Mapping[str, str] = MappingProxyType(
    {
        "hessian": "hessian_uuid_splits.csv.gz",
        "mbis": "mbis_uuid_splits.csv.gz",
        "torsion-scan": "torsion_scan_splits.csv.gz",
    }
)

_IDENTITY_FILENAME = "identity_splits.csv.gz"
_UUID_COLUMN = "uuid"
_IDENTITY_COLUMN = "identity"
_SPLIT_COLUMN = "split"


class SplitProvenanceMismatch(ConveyorError):
    """A split table does not agree with the record its own producer wrote.

    Raised when ``metadata.json`` is absent or unreadable, when it does not
    record the file being loaded, when the file's bytes hash to something other
    than the recorded value, or when a file that *does* verify no longer carries
    the columns this reader knows. Every message names the file, because the
    only useful next step is to re-run the derivation that produced it.
    """


def _text(metadata: Mapping[str, object], name: str, path: Path) -> str:
    """Read one string field of ``metadata.json``, refusing any other type."""
    value = metadata.get(name)
    if not isinstance(value, str):
        raise SplitProvenanceMismatch(
            f"{path} records {name!r} as {value!r}; a split derivation's provenance "
            f"field must be a string. Re-run {_GENERATOR_COMMAND} rather than editing it."
        )
    return value


@dataclass(frozen=True)
class SplitProvenance:
    """Which split derivation a table came from, as its producer recorded it.

    Every field is copied verbatim out of ``metadata.json``; nothing here is
    inferred, defaulted or normalised, so a provenance stamp travelling with a
    roster says exactly what the derivation said about itself.

    Attributes:
        coordinate: The derivation's MolHub coordinate, e.g.
            ``"dataset:molcrafts/class1-universal-splits@1"``.
        seed: The seed that fixed the shuffle, so the assignment is re-derivable.
        ratios: The declared train/val/test proportions and the level they were
            applied at, e.g. ``"8:1:1 train:val:test, molecule level"``.
        generator: The script that wrote the tables.
        output_sha256: Digest per output filename, as recorded — the whole
            block, not only the file one instance happened to load, so a caller
            can tell which sibling tables belong to the same derivation.
    """

    coordinate: str
    seed: int
    ratios: str
    generator: str
    output_sha256: Mapping[str, Digest]

    @classmethod
    def from_metadata(cls, root: Path) -> SplitProvenance:
        """Read ``metadata.json`` from the derivation directory *root*.

        Args:
            root: Directory holding the split tables and their ``metadata.json``.

        Returns:
            The provenance the derivation recorded for itself.

        Raises:
            SplitProvenanceMismatch: If the file is missing, is not a JSON
                object, or carries a field of the wrong shape. A directory
                whose record cannot be read is never loaded unverified — an
                unverifiable table is worse than no table, because it looks
                exactly like a good one.
        """
        path = root / _METADATA_FILENAME
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as error:
            raise SplitProvenanceMismatch(
                f"{path} could not be read ({error}); without it a split table has nothing "
                "to be verified against, and an unverified split assignment silently routes "
                f"molecules for a whole run. Re-run {_GENERATOR_COMMAND} to rewrite "
                f"{_METADATA_FILENAME}."
            ) from error
        try:
            metadata = json.loads(raw)
        except ValueError as error:
            raise SplitProvenanceMismatch(f"{path} is not valid JSON ({error}).") from error
        if not isinstance(metadata, Mapping):
            raise SplitProvenanceMismatch(
                f"{path} holds a JSON {type(metadata).__name__}, not an object."
            )

        seed = metadata.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise SplitProvenanceMismatch(
                f"{path} records seed {seed!r}; a split derivation's seed is the whole "
                "number that makes its assignment re-derivable."
            )

        recorded = metadata.get("output_sha256")
        if not isinstance(recorded, Mapping):
            raise SplitProvenanceMismatch(
                f"{path} records no 'output_sha256' block, so none of the tables beside it "
                "can be checked against what was written."
            )
        digests: dict[str, Digest] = {}
        for name, hexdigest in recorded.items():
            try:
                digests[str(name)] = Digest.sha256(str(hexdigest))
            except InvalidDigest as error:
                raise SplitProvenanceMismatch(
                    f"{path} records an unusable sha256 for {name!r} ({error})."
                ) from error

        return cls(
            coordinate=_text(metadata, "coordinate", path),
            seed=seed,
            ratios=_text(metadata, "ratios", path),
            generator=_text(metadata, "generator", path),
            output_sha256=MappingProxyType(digests),
        )

    def verify(self, path: Path) -> None:
        """Check that *path*'s bytes are the ones this derivation recorded.

        Args:
            path: One of the derivation's output tables.

        Raises:
            SplitProvenanceMismatch: If the file is absent from the record,
                cannot be read, or hashes to something else.
        """
        recorded = self.output_sha256.get(path.name)
        if recorded is None:
            raise SplitProvenanceMismatch(
                f"{path} is not one of the outputs {_METADATA_FILENAME} records "
                f"({sorted(self.output_sha256)}), so nothing states what its bytes "
                "should be."
            )
        try:
            actual = Digest.of_file(path, algorithm=recorded.algorithm)
        except OSError as error:
            raise SplitProvenanceMismatch(
                f"{path} could not be read for verification ({error}), although "
                f"{_METADATA_FILENAME} records it."
            ) from error
        if not actual.matches(recorded):
            raise SplitProvenanceMismatch(
                f"{path} hashes to {actual}, but its own producer recorded {recorded} in "
                f"{_METADATA_FILENAME}. These bytes changed after they were written; "
                f"rewrite the derivation with {_GENERATOR_COMMAND} rather than loading a "
                f"split assignment nobody can reproduce (this one records its generator as "
                f"{self.generator!r})."
            )


class _SplitTable:
    """One split table: key to split label, with the provenance it verified under.

    Built through :meth:`from_derived` (uuid-keyed, one source) or
    :meth:`from_identity` (identity-keyed). Direct construction is available for
    a caller that already holds both halves, but the alternate constructors are
    the ones that do the provenance check, so they are the ones to use.

    Args:
        assignments: Key to split label. Copied, so a later mutation of the
            caller's mapping cannot change an assignment already reported.
        provenance: The derivation record the table was verified against.
        filename: The table's own filename, carried for error messages so a
            missing key says which table was asked.
    """

    def __init__(
        self,
        assignments: Mapping[str, str],
        provenance: SplitProvenance,
        *,
        filename: str,
    ) -> None:
        self._assignments: Mapping[str, str] = MappingProxyType(dict(assignments))
        self._provenance = provenance
        self._filename = filename

    @classmethod
    def from_derived(cls, root: Path, *, source: str) -> _SplitTable:
        """Load the uuid-keyed table *source* publishes under *root*.

        Args:
            root: The derivation directory, e.g.
                ``$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1``.
            source: Which upstream source's table to load — one of ``hessian``,
                ``mbis``, ``torsion-scan``.

        Returns:
            The table for that source, keyed by scan/record uuid.

        Raises:
            KeyError: If *source* is not one this derivation publishes. The
                filenames are irregular, so there is no glob to fall back on.
            SplitProvenanceMismatch: If the table does not match ``metadata.json``.
        """
        filename = _SOURCE_FILENAMES.get(source)
        if filename is None:
            raise KeyError(
                f"Unknown split source {source!r}; this derivation publishes "
                f"{sorted(_SOURCE_FILENAMES)}. Their filenames are irregular, so there is "
                "no glob to guess with."
            )
        return cls._load(Path(root), filename, key_column=_UUID_COLUMN)

    @classmethod
    def from_identity(cls, root: Path) -> _SplitTable:
        """Load the identity-keyed table under *root*.

        This is the molecule-level assignment every per-source table was folded
        from, and the one a prepare stage routes by.

        Args:
            root: The derivation directory.

        Returns:
            The table keyed by molecule identity. It holds no uuids: asking it
            for one raises, rather than quietly reporting a split for a key it
            never had.

        Raises:
            SplitProvenanceMismatch: If the table does not match ``metadata.json``.
        """
        return cls._load(Path(root), _IDENTITY_FILENAME, key_column=_IDENTITY_COLUMN)

    @property
    def provenance(self) -> SplitProvenance:
        """The derivation record this table verified against."""
        return self._provenance

    def split_of(self, key: str) -> str:
        """Return the split label recorded for *key*.

        Args:
            key: A uuid for a table from :meth:`from_derived`, a molecule
                identity for one from :meth:`from_identity`.

        Returns:
            ``"train"``, ``"val"`` or ``"test"``, as recorded.

        Raises:
            KeyError: If this table has no row for *key*. There is no default:
                an unknown key means the caller is holding the wrong table or
                the wrong key space, and a fabricated split would leak between
                train and test without anything to detect it. The message names
                the key and the table, never the table's contents — these files
                run to millions of rows.
        """
        try:
            return self._assignments[key]
        except KeyError:
            raise KeyError(
                f"{key!r} has no row in {self._filename}. This table holds one key space "
                "only; check that the key and the table came from the same source."
            ) from None

    def counts(self) -> Mapping[str, int]:
        """How many keys each split label holds.

        Returns:
            A read-only mapping from split label to row count, folded from the
            rows themselves rather than read from ``metadata.json`` — so it
            describes the table that was loaded, not the one that was recorded.
        """
        tally: dict[str, int] = {}
        for split in self._assignments.values():
            tally[split] = tally.get(split, 0) + 1
        return MappingProxyType(tally)

    @classmethod
    def _load(cls, root: Path, filename: str, *, key_column: str) -> _SplitTable:
        """Verify one table against ``metadata.json``, then parse it.

        Verification strictly precedes parsing: bytes that are not the recorded
        ones are refused by name, instead of surfacing as a gzip or CSV error
        that says nothing about which file was wrong.
        """
        provenance = SplitProvenance.from_metadata(root)
        path = root / filename
        provenance.verify(path)

        assignments: dict[str, str] = {}
        with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header is None or key_column not in header or _SPLIT_COLUMN not in header:
                raise SplitProvenanceMismatch(
                    f"{path} verified against {_METADATA_FILENAME} but its header is "
                    f"{header!r}, without a {key_column!r} and a {_SPLIT_COLUMN!r} column. "
                    "The generator's output format moved without its version moving."
                )
            key_at = header.index(key_column)
            split_at = header.index(_SPLIT_COLUMN)
            for row in reader:
                if len(row) <= max(key_at, split_at):
                    continue
                assignments[row[key_at]] = row[split_at]
        return cls(assignments, provenance, filename=filename)
