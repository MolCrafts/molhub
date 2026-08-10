"""Typed graph-level metadata interop for molpy >= 0.12.

molpy stores a :class:`~molpy.Frame`'s graph-level metadata as
``dict[str, MetaValue]``, where every entry carries an explicit dtype tag.
Two properties of that API make naive use dangerous, and both fail *silently*:

* ``Frame.meta`` returns a **freshly built** dict on every read. In-place
  mutation — ``frame.meta[k] = v``, ``frame.meta.update(...)``,
  ``frame.meta.clear()`` — writes to a throwaway object and is discarded
  without error. Metadata must be assigned wholesale: ``frame.meta = {...}``.
* Assignment rejects plain Python values; every entry must be a ``MetaValue``
  built with one of the dtype tags molpy recognises (``str`` is *not* one of
  them — the string tag is spelled ``string``).

Two types divide that knowledge:

* :class:`MetaCodec` — converts between plain Python values and ``MetaValue``.
* :class:`Targets` — the graph-level targets *of one frame*, read and written
  through the assignment-only contract.

Call sites use :class:`Targets` and never construct a ``MetaValue``.
"""

from __future__ import annotations

from typing import Any, Iterator, Mapping

import numpy as np
from molpy import Frame
from molrs._lib import MetaValue

__all__ = ["MetaCodec", "Targets"]


class MetaCodec:
    """Translates plain Python values to and from molpy ``MetaValue`` entries.

    Stateless and reusable; :class:`Targets` holds one shared default instance.
    Construct your own only to alter the dtype mapping.
    """

    # ``bool`` must precede ``int``: ``isinstance(True, int)`` is True.
    _DTYPE_BY_TYPE: tuple[tuple[type, str], ...] = (
        (bool, "bool"),
        (int, "i64"),
        (float, "f64"),
        (str, "string"),
    )

    def encode(self, values: Mapping[str, Any]) -> dict[str, MetaValue]:
        """Wrap plain Python values as typed molpy metadata entries.

        Args:
            values: Mapping of key to a ``bool``, ``int``, ``float``, ``str``,
                or the numpy scalar equivalent of one of those.

        Returns:
            A mapping suitable for assignment to ``Frame.meta``.

        Raises:
            TypeError: If a value has a type molpy metadata cannot represent.
        """
        encoded: dict[str, MetaValue] = {}
        for key, raw in values.items():
            value = self._to_python(raw)
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

    def decode(self, meta: Mapping[str, MetaValue]) -> dict[str, Any]:
        """Unwrap typed molpy metadata into plain Python values.

        Args:
            meta: The mapping returned by ``Frame.meta``.

        Returns:
            Mapping of key to a plain Python value.
        """
        return {key: value.value for key, value in meta.items()}

    @staticmethod
    def _to_python(value: Any) -> Any:
        """Reduce numpy scalars to their plain-Python counterparts."""
        return value.item() if isinstance(value, np.generic) else value


class Targets:
    """The graph-level targets of one :class:`~molpy.Frame`.

    A thin, cheap view — construct it wherever you need to touch a frame's
    metadata; it holds no state beyond the frame and codec it was given::

        Targets(frame).write({"energy": -40.5})
        Targets(frame)["energy"]        # -> -40.5
        Targets(frame).read()           # -> {"energy": -40.5}

    Writes **replace** rather than merge, mirroring molpy's assignment-only
    semantics. Mutating ``frame.meta`` directly does nothing; always route
    writes through :meth:`write`.
    """

    def __init__(self, frame: Frame, *, codec: MetaCodec | None = None) -> None:
        self._frame = frame
        self._codec = codec or MetaCodec()

    def read(self) -> dict[str, Any]:
        """Return every target as a plain Python value."""
        return self._codec.decode(self._frame.meta)

    def write(self, values: Mapping[str, Any]) -> None:
        """Replace all targets with *values*.

        Args:
            values: Plain Python values, as accepted by :meth:`MetaCodec.encode`.

        Raises:
            TypeError: If a value has a type molpy metadata cannot represent.
        """
        self._frame.meta = self._codec.encode(values)

    def __getitem__(self, key: str) -> Any:
        """Return one target value.

        Raises:
            KeyError: If *key* is not a target of this frame.
        """
        return self.read()[key]

    def __contains__(self, key: str) -> bool:
        return key in self._frame.meta

    def __iter__(self) -> Iterator[str]:
        return iter(self._frame.meta)

    def __len__(self) -> int:
        return len(self._frame.meta)

    def keys(self) -> list[str]:
        """Return the target names present on this frame."""
        return list(self._frame.meta)
