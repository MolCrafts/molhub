"""molrec frame bytes on numpy — mirrors ``src/molhub/io/frame_bytes.py``."""

from __future__ import annotations

import numpy as np
import pytest

from molhub.io import frame_bytes


class TestFrameBytes:
    def test_round_trip_keeps_dtype_shape_strings_and_meta(self) -> None:
        blocks = {
            "atoms": {
                "flag": np.array([1, 0, 1], dtype=np.int8),
                "x": np.array([0.0, 1.5, 3.0]),
                "xyz": np.arange(9, dtype=np.float32).reshape(3, 3),
                "element": np.array(["O", "H", "H"]),
            }
        }
        value = frame_bytes.encode(blocks, {"pe": -1.25, "tag": "a"}, step=7)
        decoded = frame_bytes.decode(value)
        for name, array in blocks["atoms"].items():
            got = decoded.blocks["atoms"][name]
            assert got.shape == array.shape and np.array_equal(got, array)
            if array.dtype.kind != "U":
                assert got.dtype == array.dtype
        assert decoded.meta == {"pe": -1.25, "tag": "a"} and decoded.step == 7

    def test_a_foreign_magic_is_refused(self) -> None:
        value = bytearray(frame_bytes.encode({}, {}))
        value[:4] = b"NOPE"
        with pytest.raises(ValueError, match="magic"):
            frame_bytes.decode(bytes(value))

    def test_a_dtype_outside_molrec_is_refused(self) -> None:
        with pytest.raises(ValueError, match="closed dtype set"):
            frame_bytes.encode({"atoms": {"t": np.array([1], dtype="datetime64[s]")}}, {})
