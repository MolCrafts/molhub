"""Typed failures of the prepare stage — one type per distinguishable defect.

Follows :mod:`molhub.sources.errors`: a failure gets its own class exactly when
a caller can reasonably act differently on it. The conveyor driver's five
reactions are genuinely different, which is why there are five types and not one
``PrepareError`` with a string:

* :class:`UnsupportedRecordError` — this *source* has no encoder yet. The shard
  is not broken; the roster should not have routed it here.
* :class:`IncompleteRecordError` — this *record* cannot become a unit without
  inventing data. The shard is suspect and its digest is worth re-checking.
* :class:`UnroutableUnitError` — the *split table* and the shard disagree about
  which molecules exist. Re-running the prepare stage will fail identically
  until the right ``class1-universal-splits`` version is loaded.
* :class:`IncompleteProvenanceError` — the *caller* built the job wrong; it
  fires before a writer is opened, so nothing on disk needs cleaning up.
* :class:`BlockFormatError` — the *sealed block* does not witness what molhub is
  about to record as READY. The block must never reach the ledger.

All five derive from :class:`~molhub.conveyor.block.ConveyorError`, so a driver
that only wants "the prepare stage refused this shard" can still catch one type.
"""

from __future__ import annotations

from molhub.conveyor.block import ConveyorError

__all__ = [
    "PrepareError",
    "UnsupportedRecordError",
    "IncompleteRecordError",
    "UnroutableUnitError",
    "IncompleteProvenanceError",
    "BlockFormatError",
]


class PrepareError(ConveyorError):
    """Base class for every prepare-stage failure."""


class UnsupportedRecordError(PrepareError):
    """A record this encoder has no columns for.

    Raised at *construction* for ``THEMolUnitEncoder(task="mbis")`` — whose
    atom-level electrostatics targets need column routes ``molix.block/1`` does
    not define — and at ``encode`` for anything that is not a
    :data:`~molpy.FrameCollection`. Encoding either "as far as it goes" would
    produce a unit that silently lost its targets.

    The MBIS refusal is keyed on the task rather than on the record because a
    record is a molpy object: after ``hf-facade-02-frame-records`` an MBIS frame
    and a hessian frame are the same type, and one shard is one task.
    """


class IncompleteRecordError(PrepareError):
    """A record cannot be encoded without fabricating chemistry or geometry.

    Raised when a molecule carries bonds but no integer bond order, when a
    trajectory's frames disagree with the topology's atom count (the ``k * N``
    stride is what makes the two-level block layout valid), when a frame is
    missing a target the rest of the unit declares, or when the molecular
    identity's only input — ``mapped_isomeric_smiles`` — is absent.
    """


class UnroutableUnitError(PrepareError):
    """A unit's molecular identity has no split assignment.

    There is no default split and no "assume train": streaming never re-splits
    (I7), so a molecule the split table does not know is refused by name rather
    than routed by guess. The message names both the identity and the unit key,
    because the two answer different questions — which molecule is missing from
    the table, and which record made that visible.
    """


class IncompleteProvenanceError(PrepareError):
    """Provenance is missing a key molnex's block format requires.

    ``molix.block/1`` validates the presence of ``source`` / ``generator`` /
    ``created_at`` / ``units`` and nothing about their contents. molhub checks
    the same four keys **before** opening a writer, so the defect surfaces even
    in an environment where molnex is not importable, and never halfway through
    a shard.
    """


class BlockFormatError(PrepareError):
    """A sealed block does not witness the READY record molhub would write.

    Raised when ``manifest.json`` is unreadable, declares a format other than
    ``molix.block/1``, is not ``sealed``, names a split other than the one the
    writer was constructed with, reports a unit count the writer disagrees with,
    or carries no ``block_digest``. molhub does not recompute the digest —
    recomputation is ``BlockReader.verify()``'s job in molnex — so these five
    fields are the whole of the cross-repo format coupling.
    """
