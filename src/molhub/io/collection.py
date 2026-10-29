"""What an mrec collection means, shared by the LMDB and HDF5 backends.

Each backend owns its bytes on disk. A record is the same thing in both: a
system written once, one self-describing frame blob per step holding only the
blocks that changed, and one sequence declaration for the whole collection.
Keeping that here is what stops the two writers from drifting.

A molpy ``Frame`` is built only in :func:`assemble`, on the caller's thread.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import numpy as np

from molhub.io import frame_bytes

_LOCKS = threading.Lock()


def instance_lock(obj: Any) -> threading.Lock:
    """A lock created on first use.

    Stored as ``_lock_obj``. A pickle must drop that attribute: a
    ``threading.Lock`` does not pickle, and creating it lazily means a
    restored object needs no ``__setstate__``.
    """
    lock = getattr(obj, "_lock_obj", None)
    if lock is None:
        with _LOCKS:
            lock = getattr(obj, "_lock_obj", None)
            if lock is None:
                lock = obj._lock_obj = threading.Lock()
    return lock


class RecordBytes:
    """One record, already checked against the collection and encoded."""

    __slots__ = ("frames", "index", "n_atoms", "schema", "system")

    def __init__(
        self,
        *,
        system: bytes | None,
        frames: tuple[bytes, ...],
        n_atoms: int,
        schema: dict[str, Any],
        index: dict[str, Any],
    ) -> None:
        self.system = system
        self.frames = frames
        self.n_atoms = n_atoms
        self.schema = schema
        self.index = index


def _blocks_of(frame: Any) -> dict[str, dict[str, np.ndarray]]:
    return {
        name: {column: np.asarray(frame[name][column]) for column in frame[name].keys()}
        for name in frame.keys()
    }


def _meta_of(frame: Any) -> dict[str, Any]:
    return {key: getattr(value, "value", value) for key, value in frame.meta.items()}


def _meta_tag(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "bool"
    if isinstance(value, (int, np.integer)):
        return "i64"
    if isinstance(value, (float, np.floating)):
        return "f64"
    if isinstance(value, str):
        return "string"
    return "json"


def _jsonable(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value


def _same(a: dict[str, np.ndarray], b: dict[str, np.ndarray]) -> bool:
    return a.keys() == b.keys() and all(
        a[k].dtype == b[k].dtype and a[k].shape == b[k].shape and np.array_equal(a[k], b[k])
        for k in a
    )


def _schema_of(
    states: list[dict[str, dict[str, np.ndarray]]], metas: list[dict[str, Any]]
) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    for state in states:
        for name, columns in state.items():
            declared = {
                column: {
                    "dtype": frame_bytes.spec_dtype(array),
                    "trailing": list(array.shape[1:]),
                }
                for column, array in columns.items()
            }
            if blocks.setdefault(name, {"columns": declared})["columns"] != declared:
                raise ValueError(f"block {name!r} changes its columns within a record")
    meta: dict[str, Any] = {}
    for values in metas:
        for key, value in values.items():
            meta.setdefault(key, {"dtype": _meta_tag(value)})
    return {"blocks": blocks, "meta": meta}


def _align(
    fixed: dict[str, dict[str, np.ndarray]], states: list[dict[str, dict[str, np.ndarray]]]
) -> None:
    for name, columns in fixed.items():
        rows = len(next(iter(columns.values()))) if columns else 0
        for state in states:
            if name not in state:
                continue
            shared = set(state[name]) & set(columns)
            if shared:
                raise ValueError(f"columns {sorted(shared)} of {name!r} are in system and frames")
            if state[name] and len(next(iter(state[name].values()))) != rows:
                raise ValueError(f"frame block {name!r} and system block disagree on rows")


def encode_record(
    frames: Sequence[Any],
    *,
    system: Any | None,
    steps: Sequence[int] | None,
    index: Mapping[str, Any] | None,
    schema: dict[str, Any] | None,
    index_names: Iterable[str] | None,
    record_index: int,
) -> RecordBytes:
    """Validate one record and encode its system and per-frame deltas.

    The first record's declaration and index columns are the collection's.
    A later record that declares anything else is refused. Frame blobs hold
    only the blocks that changed since the previous frame of this record.

    Raises:
        ValueError: Steps do not increase, the declaration or the index
            columns differ from the collection, or a system block and a frame
            block disagree.
    """
    numbered = list(range(len(frames))) if steps is None else [int(n) for n in steps]
    if len(numbered) != len(frames) or any(b <= a for a, b in zip(numbered, numbered[1:])):
        raise ValueError(f"steps must increase strictly, one per frame; got {numbered}")
    states = [_blocks_of(frame) for frame in frames]
    metas = [_meta_of(frame) for frame in frames]
    fixed = _blocks_of(system) if system is not None else {}
    declared = _schema_of(states, metas)
    if schema is None:
        schema = declared
    elif declared != schema and states:
        raise ValueError(
            f"record {record_index} declares {declared}, the collection {schema}; "
            "every record in a collection uses one declaration"
        )
    _align(fixed, states)
    entry = dict(index or {})
    if index_names is not None and set(entry) != set(index_names):
        raise ValueError(f"index columns {sorted(entry)} differ from {sorted(index_names)}")
    carried: dict[str, dict[str, np.ndarray]] = {}
    blobs: list[bytes] = []
    for state, meta, step in zip(states, metas, numbered):
        changed = {
            name: cols
            for name, cols in state.items()
            if name not in carried or not _same(carried[name], cols)
        }
        carried.update(state)
        encoded_meta = {key: _jsonable(value) for key, value in meta.items()}
        blobs.append(frame_bytes.encode(changed, encoded_meta, step=step))
    atoms = fixed.get("atoms") or (states[0].get("atoms") if states else None) or {}
    n_atoms = len(next(iter(atoms.values()))) if atoms else 0
    system_blob = None
    if system is not None:
        system_blob = frame_bytes.encode(
            fixed, {key: _jsonable(value) for key, value in _meta_of(system).items()}
        )
    return RecordBytes(
        system=system_blob,
        frames=tuple(blobs),
        n_atoms=n_atoms,
        schema=schema,
        index=entry,
    )


def write_records(writer: Any, records: Sequence[Mapping[str, Any]]) -> None:
    """Append each mapping.

    A record carries ``frames`` and, optionally, ``system``, ``steps``,
    ``index`` and ``record_meta``.
    """
    for record in records:
        writer.write_record(
            record["frames"],
            system=record.get("system"),
            steps=record.get("steps"),
            index=record.get("index"),
            record_meta=record.get("record_meta"),
        )


def assemble(system: Any | None, updates: Sequence[Any]) -> tuple[Any, ...]:
    """Merge a system and carried-forward frame updates into molpy frames.

    No updates yields one frame of the system. Otherwise each frame is the
    system's blocks overlaid with every block seen up to that step, and its
    meta is the system's, the step's, and ``step``.
    """
    from molpy import Block, Frame

    fixed = {} if system is None else system.blocks
    base_meta = {} if system is None else system.meta
    if not updates:
        frame = Frame()
        for name, columns in fixed.items():
            frame[name] = Block({column: np.array(values) for column, values in columns.items()})
        frame.meta = dict(base_meta)
        return (frame,)
    frames: list[Any] = []
    carried: dict[str, dict[str, np.ndarray]] = {}
    for update in updates:
        carried.update(update.blocks)
        frame = Frame()
        for name in dict.fromkeys([*fixed, *carried]):
            columns = {**fixed.get(name, {}), **carried.get(name, {})}
            frame[name] = Block({column: np.array(values) for column, values in columns.items()})
        frame.meta = {**base_meta, **update.meta, "step": int(update.step)}
        frames.append(frame)
    return tuple(frames)


def realize_record(staged: tuple[bytes | None, Sequence[bytes]]) -> tuple[Any, ...]:
    """Decode staged system and frame blobs and :func:`assemble` them."""
    system_raw, frame_raws = staged
    system = frame_bytes.decode(system_raw) if system_raw is not None else None
    updates = [frame_bytes.decode(raw) for raw in frame_raws]
    return assemble(system, updates)


def _box_of(frame: Any) -> dict[str, Any] | None:
    box = getattr(frame, "box", None)
    if box is None:
        return None
    return {
        "vectors": np.asarray(box.matrix, dtype=np.float64),
        "origin": np.asarray(box.origin, dtype=np.float64),
        "boundary": [bool(flag) for flag in np.asarray(box.pbc).reshape(3)],
        "cell_defined": bool(box.is_cell_defined),
    }


def encode_sample(frames: Sequence[Any]) -> bytes:
    """One sample as frame-sequence bytes: blocks, meta, and box.

    The caller stores the bytes. This function does not open a file.
    """
    parts = []
    for frame in frames:
        meta = {key: _jsonable(value) for key, value in _meta_of(frame).items()}
        parts.append((_blocks_of(frame), meta, _box_of(frame)))
    return frame_bytes.encode_frames(parts)


def decode_sample(payload: bytes) -> tuple[Any, ...]:
    """Rebuild the frames :func:`encode_sample` stored, on this thread.

    Columns are writable copies.

    Raises:
        ValueError: *payload* is not a frame sequence, or a frame inside it
            does not decode.
    """
    from molpy import Block, Box, Frame
    from molpy.core import Cell

    frames: list[Any] = []
    for decoded in frame_bytes.decode_frames(payload):
        frame = Frame()
        for name, columns in decoded.blocks.items():
            frame[name] = Block({column: np.array(values) for column, values in columns.items()})
        frame.meta = dict(decoded.meta)
        if decoded.box is not None:
            spec = decoded.box
            defined = bool(spec.get("cell_defined", True))
            cell = (
                Cell.matrix(np.asarray(spec["vectors"], dtype=np.float64))
                if defined
                else Cell.undefined()
            )
            frame.box = Box(
                cell,
                pbc=np.asarray(spec["boundary"], dtype=bool),
                origin=np.asarray(spec["origin"], dtype=np.float64),
            )
        frames.append(frame)
    return tuple(frames)
