"""molrec frame bytes on plain numpy.

One frame is molrec's encoding (``docs/spec/lmdb.md``, "Frame bytes")::

    value := "MRF1" | u32le header_length | UTF-8 JSON header | pad to 8 | column buffers

Every numeric column is one C-order little-endian buffer at an 8-byte-aligned
offset into the payload, so decoding is ``numpy.frombuffer`` on the value —
no copy, no per-column validation. A string column lives in the header.

A sequence of those values is ``"MRFS" | u32le count | (u32le length | MRF1)*``.
Nothing here names a file or a store. molrec's own codec
(``molrec.core.bindings.lmdb``) is the arbiter of one frame; this module is
molhub's implementation of it, kept to numpy so a training loader can decode
a record without paying for pydantic models it never uses.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

__all__ = [
    "DecodedFrame",
    "decode",
    "decode_frames",
    "encode",
    "encode_frames",
    "spec_dtype",
]

MAGIC = b"MRF1"
FRAMES_MAGIC = b"MRFS"
ALIGN = 8
_HEADER = struct.Struct("<4sI")
_U32 = struct.Struct("<I")

#: molrec's closed dtype set, spec name -> numpy name.
NUMPY_DTYPE: dict[str, str] = {
    "f16": "float16",
    "f32": "float32",
    "f64": "float64",
    "i8": "int8",
    "i16": "int16",
    "i32": "int32",
    "i64": "int64",
    "u8": "uint8",
    "u16": "uint16",
    "u32": "uint32",
    "u64": "uint64",
    "bool": "bool",
    "c64": "complex64",
    "c128": "complex128",
}
_SPEC_DTYPE = {numpy: spec for spec, numpy in NUMPY_DTYPE.items()}

Columns = dict[str, np.ndarray]


def spec_dtype(array: np.ndarray) -> str:
    """The molrec dtype name of *array*.

    Raises:
        ValueError: The dtype is outside molrec's closed set.
    """
    dtype = np.asarray(array).dtype
    if dtype.kind in ("U", "S", "O", "T"):
        return "string"
    name = _SPEC_DTYPE.get(dtype.name)
    if name is None:
        raise ValueError(f"dtype {dtype.name!r} is outside molrec's closed dtype set")
    return name


class DecodedFrame:
    """What one value holds: blocks of columns, meta, and the trajectory fields."""

    __slots__ = ("blocks", "meta", "step", "time", "box")

    def __init__(
        self,
        blocks: dict[str, Columns],
        meta: dict[str, Any],
        step: int | None,
        time: float | None,
        box: dict[str, Any] | None,
    ) -> None:
        self.blocks = blocks
        self.meta = meta
        self.step = step
        self.time = time
        self.box = box


def encode(
    blocks: Mapping[str, Mapping[str, np.ndarray]],
    meta: Mapping[str, Any],
    *,
    step: int | None = None,
    time: float | None = None,
    box: Mapping[str, Any] | None = None,
) -> bytes:
    """Encode one frame.

    Args:
        blocks: Block name -> column name -> array; every column of a block
            shares its leading length.
        meta: A JSON-serialisable meta document.
        step: A trajectory update's step number.
        time: A trajectory update's time.
        box: ``{"vectors", "origin", "boundary", "cell_defined"}`` when stated.

    Returns:
        The value.

    Raises:
        ValueError: Columns of one block disagree on their row count, or a
            dtype is outside molrec's set.
    """
    header_blocks: dict[str, Any] = {}
    buffers: list[bytes] = []
    offset = 0
    for name, columns in blocks.items():
        count: int | None = None
        entries: dict[str, Any] = {}
        for column, values in columns.items():
            array = np.asarray(values)
            if array.ndim == 0:
                raise ValueError(f"{name}/{column} is a scalar; a column has a leading axis")
            if count is None:
                count = int(array.shape[0])
            elif int(array.shape[0]) != count:
                raise ValueError(f"{name}/{column} has {array.shape[0]} rows, block has {count}")
            dtype = spec_dtype(array)
            entry: dict[str, Any] = {"dtype": dtype, "shape": list(array.shape)}
            if dtype == "string":
                entry["values"] = array.astype(str).ravel().tolist()
            else:
                raw = np.ascontiguousarray(
                    array, dtype=np.dtype(NUMPY_DTYPE[dtype]).newbyteorder("<")
                ).tobytes()
                entry["offset"] = offset
                pad = (-len(raw)) % ALIGN
                buffers.append(raw + b"\0" * pad)
                offset += len(raw) + pad
            entries[column] = entry
        header_blocks[name] = {"count": count or 0, "structural_shape": None, "columns": entries}
    header: dict[str, Any] = {"blocks": header_blocks, "meta": dict(meta)}
    if step is not None:
        header["step"] = int(step)
    if time is not None:
        header["time"] = float(time)
    if box is not None:
        header["box"] = {
            "vectors": np.asarray(box["vectors"], dtype="float64").tolist(),
            "origin": np.asarray(box.get("origin", np.zeros(3)), dtype="float64").tolist(),
            "boundary": [bool(flag) for flag in box.get("boundary", (True, True, True))],
            "cell_defined": bool(box.get("cell_defined", True)),
        }
    text = json.dumps(header, separators=(",", ":")).encode()
    head = _HEADER.pack(MAGIC, len(text)) + text
    return head + b"\0" * ((-len(head)) % ALIGN) + b"".join(buffers)


def decode(value: bytes | memoryview) -> DecodedFrame:
    """Decode one value; numeric columns are read-only views into it.

    Raises:
        ValueError: A foreign magic, a dtype outside the set, a misaligned
            offset, or a buffer running past the value.
    """
    view = memoryview(value)
    if len(view) < _HEADER.size:
        raise ValueError("frame bytes shorter than their fixed header")
    magic, length = _HEADER.unpack_from(view, 0)
    if magic != MAGIC:
        raise ValueError(f"frame bytes carry magic {bytes(magic)!r}, expected {MAGIC!r}")
    header = json.loads(bytes(view[_HEADER.size : _HEADER.size + length]))
    payload = _HEADER.size + length
    payload += (-payload) % ALIGN
    blocks: dict[str, Columns] = {}
    for name, entry in header["blocks"].items():
        columns: Columns = {}
        for column, spec in entry["columns"].items():
            dtype = spec["dtype"]
            shape = tuple(int(n) for n in spec["shape"])
            if dtype == "string":
                columns[column] = np.asarray(spec["values"], dtype=str).reshape(shape)
                continue
            if dtype not in NUMPY_DTYPE:
                raise ValueError(f"{name}/{column}: dtype {dtype!r} is outside molrec's set")
            at = int(spec["offset"])
            if at % ALIGN:
                raise ValueError(f"{name}/{column}: offset {at} is not a multiple of {ALIGN}")
            numpy_dtype = np.dtype(NUMPY_DTYPE[dtype]).newbyteorder("<")
            count = int(np.prod(shape))
            if payload + at + count * numpy_dtype.itemsize > len(view):
                raise ValueError(f"{name}/{column}: buffer runs past the value")
            columns[column] = np.frombuffer(
                view, dtype=numpy_dtype, count=count, offset=payload + at
            ).reshape(shape)
        blocks[name] = columns
    return DecodedFrame(
        blocks=blocks,
        meta=header.get("meta", {}),
        step=header.get("step"),
        time=header.get("time"),
        box=header.get("box"),
    )


def encode_frames(
    frames: Sequence[
        tuple[Mapping[str, Mapping[str, np.ndarray]], Mapping[str, Any], Mapping[str, Any] | None]
    ],
) -> bytes:
    """Encode a sequence of frames as one byte string.

    Each item is ``(blocks, meta, box)``. ``box`` is None when the frame has
    none. The bytes name no store.

    Args:
        frames: Frames in order. An empty sequence encodes as a count of zero.
    """
    chunks: list[bytes] = []
    for blocks, meta, box in frames:
        blob = encode(blocks, meta, box=box)
        chunks.append(_U32.pack(len(blob)) + blob)
    return FRAMES_MAGIC + _U32.pack(len(chunks)) + b"".join(chunks)


def decode_frames(payload: bytes | memoryview) -> tuple[DecodedFrame, ...]:
    """Decode a value written by :func:`encode_frames`.

    Raises:
        ValueError: A foreign magic, a length that runs past the value, or a
            frame :func:`decode` refuses.
    """
    view = memoryview(payload)
    if (
        len(view) < len(FRAMES_MAGIC) + _U32.size
        or bytes(view[: len(FRAMES_MAGIC)]) != FRAMES_MAGIC
    ):
        raise ValueError("frame sequence does not start with its magic")
    count = _U32.unpack_from(view, len(FRAMES_MAGIC))[0]
    at = len(FRAMES_MAGIC) + _U32.size
    frames: list[DecodedFrame] = []
    for _ in range(count):
        if at + _U32.size > len(view):
            raise ValueError("frame sequence ends inside a frame length")
        size = _U32.unpack_from(view, at)[0]
        at += _U32.size
        if at + size > len(view):
            raise ValueError("frame sequence ends inside a frame")
        frames.append(decode(view[at : at + size]))
        at += size
    if at != len(view):
        raise ValueError("frame sequence has bytes after its last frame")
    return tuple(frames)
