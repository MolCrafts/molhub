"""Typed graph-level metadata interop for molpy 0.13.

``Frame.meta`` is a *write-through view*: assigning a mapping coerces each
value into molpy's typed metadata, and reading a key hands back the plain
Python scalar (molpy 0.12 returned :class:`molpy.MetaValue` objects instead).
:class:`MetaCodec` still encodes to :class:`molpy.MetaValue` so molhub — not
molpy's coercion defaults — decides the stored dtype, and so graph-level
targets stay restricted to scalars: molpy 0.13 would also accept
fixed-length sequences, which no dataset target is.  Keep that dependency
detail behind :class:`Targets`; dataset loaders may use :func:`write_meta` as
the small assignment helper.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import numpy as np
from molpy import Frame, MetaValue

__all__ = ["MetaCodec", "Targets", "write_meta"]


class MetaCodec:
    """Encode plain scalar targets as molpy metadata and decode them again."""

    # bool must precede int because bool is an int subclass.
    _DTYPE_BY_TYPE: tuple[tuple[type, str], ...] = (
        (bool, "bool"),
        (int, "i64"),
        (float, "f64"),
        (str, "string"),
    )

    def encode(self, values: Mapping[str, Any]) -> dict[str, MetaValue]:
        """Return a mapping that can be assigned to ``Frame.meta``."""
        encoded: dict[str, MetaValue] = {}
        for key, raw in values.items():
            value = raw.item() if isinstance(raw, np.generic) else raw
            for py_type, dtype in self._DTYPE_BY_TYPE:
                if isinstance(value, py_type):
                    encoded[key] = MetaValue(dtype, value)
                    break
            else:
                raise TypeError(
                    f"Metadata key {key!r} has unsupported type "
                    f"{type(raw).__name__}; molpy metadata accepts "
                    "bool, int, float, or str."
                )
        return encoded

    def decode(self, meta: Mapping[str, object]) -> dict[str, Any]:
        """Return plain Python scalar values from a ``Frame.meta`` mapping.

        Both halves of the round trip are accepted: a ``Frame.meta`` view,
        which molpy 0.13 already unwraps to plain scalars, and the
        :class:`molpy.MetaValue` mapping :meth:`encode` produces.
        """
        return {
            key: value.value if isinstance(value, MetaValue) else value
            for key, value in meta.items()
        }


class Targets:
    """Typed graph-level targets belonging to one :class:`molpy.Frame`."""

    def __init__(self, frame: Frame, *, codec: MetaCodec | None = None) -> None:
        self._frame = frame
        self._codec = codec or MetaCodec()

    def read(self) -> dict[str, Any]:
        """Read all targets as plain Python scalar values.

        The result is detached from the frame: unlike molpy 0.13's
        write-through ``Frame.meta`` view, mutating it does not write back.
        """
        return self._codec.decode(self._frame.meta)

    def write(self, values: Mapping[str, Any]) -> None:
        """Replace all frame targets with *values*."""
        self._frame.meta = self._codec.encode(values)

    def __getitem__(self, key: str) -> Any:
        return self.read()[key]

    def __contains__(self, key: str) -> bool:
        return key in self._frame.meta

    def __iter__(self) -> Iterator[str]:
        return iter(self._frame.meta)

    def __len__(self) -> int:
        return len(self._frame.meta)

    def keys(self) -> list[str]:
        """Return target names present on the frame."""
        return list(self._frame.meta)


def write_meta(frame: Frame, values: Mapping[str, Any]) -> None:
    """Replace ``frame.meta`` from plain bool/int/float/str values."""
    Targets(frame).write(values)
