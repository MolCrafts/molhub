"""Tests for typed graph-level metadata interop."""

from __future__ import annotations

import numpy as np
import pytest
from molpy import Frame

from molhub.dataset.meta import MetaCodec, Targets


class TestMetaCodecEncode:
    def test_float(self):
        encoded = MetaCodec().encode({"energy": -40.5})
        assert encoded["energy"].dtype == "f64"
        assert encoded["energy"].value == pytest.approx(-40.5)

    def test_int(self):
        assert MetaCodec().encode({"n": 7})["n"].dtype == "i64"

    def test_bool_is_not_widened_to_int(self):
        """``isinstance(True, int)`` is True, so bool must be probed first."""
        assert MetaCodec().encode({"flag": True})["flag"].dtype == "bool"

    def test_string_uses_the_string_tag_not_str(self):
        """molpy spells the string dtype ``string``; ``str`` raises."""
        assert MetaCodec().encode({"tag": "gdb9"})["tag"].dtype == "string"

    def test_numpy_scalars_are_reduced(self):
        encoded = MetaCodec().encode({"f": np.float64(2.5), "i": np.int64(3), "b": np.bool_(True)})
        assert (encoded["f"].dtype, encoded["i"].dtype, encoded["b"].dtype) == (
            "f64",
            "i64",
            "bool",
        )

    def test_empty_mapping(self):
        assert MetaCodec().encode({}) == {}

    @pytest.mark.parametrize("bad", [None, [1, 2], {"a": 1}, (1, 2), object()])
    def test_unsupported_type_raises(self, bad):
        with pytest.raises(TypeError, match="unsupported type"):
            MetaCodec().encode({"bad": bad})

    def test_error_names_the_offending_key(self):
        with pytest.raises(TypeError, match="'culprit'"):
            MetaCodec().encode({"fine": 1.0, "culprit": None})


class TestMetaCodecDecode:
    def test_roundtrip_preserves_python_types(self):
        codec = MetaCodec()
        original = {"e": -1.5, "n": 2, "ok": False, "s": "x"}
        assert codec.decode(codec.encode(original)) == original

    def test_decode_empty(self):
        assert MetaCodec().decode({}) == {}


class TestTargetsWrite:
    def test_roundtrip(self):
        f = Frame()
        Targets(f).write({"energy": -40.5})
        assert Targets(f).read()["energy"] == pytest.approx(-40.5)

    def test_mixed_types_in_one_call(self):
        f = Frame()
        values = {"e": -1.5, "n": 2, "ok": False, "s": "x"}
        Targets(f).write(values)
        assert Targets(f).read() == values

    def test_replaces_rather_than_merges(self):
        f = Frame()
        Targets(f).write({"a": 1.0, "b": 2.0})
        Targets(f).write({"c": 3.0})
        assert Targets(f).read() == {"c": 3.0}

    def test_clearing_via_empty_mapping(self):
        f = Frame()
        Targets(f).write({"a": 1.0})
        Targets(f).write({})
        assert Targets(f).read() == {}

    def test_in_place_mutation_of_meta_does_not_persist(self):
        """Regression guard for the molpy trap this module exists to hide.

        ``Frame.meta`` returns a freshly built dict, so mutating it is a silent
        no-op. If molpy ever changes that, this test fails loudly and the
        assignment-only contract in :meth:`Targets.write` can be revisited.
        """
        f = Frame()
        Targets(f).write({"a": 1.0})
        snapshot = f.meta
        snapshot["b"] = snapshot["a"]
        assert "b" not in f.meta
        assert Targets(f).read() == {"a": 1.0}

    def test_frames_do_not_share_metadata(self):
        f, g = Frame(), Frame()
        Targets(f).write({"a": 1.0})
        Targets(g).write({"a": 2.0})
        assert Targets(f).read()["a"] == pytest.approx(1.0)
        assert Targets(g).read()["a"] == pytest.approx(2.0)

    def test_copy_isolates_metadata(self):
        f = Frame()
        Targets(f).write({"a": 1.0})
        clone = f.copy()
        Targets(clone).write({"a": 9.0})
        assert Targets(f).read()["a"] == pytest.approx(1.0)

    def test_rejects_unsupported_value(self):
        with pytest.raises(TypeError):
            Targets(Frame()).write({"bad": None})


class TestTargetsMapping:
    @pytest.fixture
    def frame(self):
        f = Frame()
        Targets(f).write({"energy": -40.5, "n": 3})
        return f

    def test_getitem(self, frame):
        assert Targets(frame)["energy"] == pytest.approx(-40.5)

    def test_getitem_missing_key_raises(self, frame):
        with pytest.raises(KeyError):
            Targets(frame)["nope"]

    def test_contains(self, frame):
        t = Targets(frame)
        assert "energy" in t
        assert "nope" not in t

    def test_len(self, frame):
        assert len(Targets(frame)) == 2

    def test_iter_and_keys_agree(self, frame):
        t = Targets(frame)
        assert sorted(t) == sorted(t.keys()) == ["energy", "n"]

    def test_empty_frame(self):
        t = Targets(Frame())
        assert len(t) == 0
        assert t.read() == {}
        assert t.keys() == []


class TestTargetsCodecInjection:
    def test_custom_codec_is_used(self):
        class WideningCodec(MetaCodec):
            """Stores every int as f64 instead of i64."""

            _DTYPE_BY_TYPE = ((bool, "bool"), (int, "f64"), (float, "f64"), (str, "string"))

        f = Frame()
        Targets(f, codec=WideningCodec()).write({"n": 3})
        assert f.meta["n"].dtype == "f64"
