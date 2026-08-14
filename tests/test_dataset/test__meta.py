"""Tests for private Frame.meta assignment."""

from __future__ import annotations

import numpy as np
import pytest
from molpy import Frame, MetaValue

from molhub.dataset._meta import MetaCodec, Targets, write_meta


class TestWriteMeta:
    def test_roundtrip(self) -> None:
        frame = Frame()
        write_meta(frame, {"energy": -40.5, "n": 2, "ok": False, "s": "x"})
        assert Targets(frame).read() == {
            "energy": -40.5,
            "n": 2,
            "ok": False,
            "s": "x",
        }

    def test_replaces(self) -> None:
        frame = Frame()
        write_meta(frame, {"a": 1.0, "b": 2.0})
        write_meta(frame, {"c": 3.0})
        assert set(frame.meta) == {"c"}
        assert Targets(frame)["c"] == pytest.approx(3.0)

    def test_in_place_mutation_persists(self) -> None:
        # molpy 0.13: ``Frame.meta`` is a write-through view, so an in-place
        # write lands on the frame (0.12 handed out a fresh mapping instead).
        frame = Frame()
        write_meta(frame, {"a": 1.0})
        view = frame.meta
        view["b"] = view["a"]
        assert "b" in frame.meta
        assert Targets(frame).read() == {"a": 1.0, "b": 1.0}

    def test_read_is_detached_from_the_frame(self) -> None:
        # What ``Targets`` owns regardless of the molpy version: the mapping
        # ``read`` hands back is a copy, so mutating it cannot reach the frame.
        frame = Frame()
        write_meta(frame, {"a": 1.0})
        snapshot = Targets(frame).read()
        snapshot["b"] = snapshot["a"]
        assert "b" not in frame.meta
        assert Targets(frame).read() == {"a": 1.0}

    def test_rejects_unsupported(self) -> None:
        with pytest.raises(TypeError, match="unsupported"):
            write_meta(Frame(), {"bad": None})


class TestMetaCodec:
    def test_uses_public_molpy_metavalue(self) -> None:
        encoded = MetaCodec().encode({"x": np.float64(2.5)})
        assert isinstance(encoded["x"], MetaValue)
        assert encoded["x"].dtype == "f64"

    def test_decode_roundtrip(self) -> None:
        values = {"n": np.int64(3), "ok": np.bool_(True), "s": "x"}
        encoded = MetaCodec().encode(values)
        assert MetaCodec().decode(encoded) == {"n": 3, "ok": True, "s": "x"}


def test_compatibility_import() -> None:
    from molhub.dataset import Targets as PublicTargets
    from molhub.dataset.meta import Targets as CompatibilityTargets

    assert PublicTargets is CompatibilityTargets is Targets
