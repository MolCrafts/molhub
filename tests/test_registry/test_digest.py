"""Tests for Digest and incremental hashing."""

from __future__ import annotations

import hashlib

import pytest

from molhub.registry.digest import Digest, Sha256Stream
from molhub.registry.errors import InvalidDigest

_BODY = b"molecular bytes"
_HEX = hashlib.sha256(_BODY).hexdigest()


class TestDigestConstruction:
    def test_sha256_classmethod(self):
        d = Digest.sha256(_HEX)
        assert d.algorithm == "sha256"
        assert d.hexdigest == _HEX

    def test_hex_is_lowercased(self):
        assert Digest.sha256(_HEX.upper()).hexdigest == _HEX

    def test_parse_prefixed_form(self):
        assert Digest.parse(f"sha256:{_HEX}") == Digest.sha256(_HEX)

    def test_parse_accepts_md5_for_upstream_reconciliation(self):
        d = Digest.parse("md5:ce2c7b2a879450cbbfff4d7ccea648f9")
        assert d.algorithm == "md5"

    def test_str_is_the_prefixed_form(self):
        assert str(Digest.sha256(_HEX)) == f"sha256:{_HEX}"

    @pytest.mark.parametrize(
        "bad",
        ["", "sha256:", "sha256:xyz", "nonsense", f"unknownalgo:{_HEX}", "sha256:abc"],
    )
    def test_rejects_malformed(self, bad):
        with pytest.raises(InvalidDigest):
            Digest.parse(bad)

    def test_rejects_wrong_length_for_sha256(self):
        with pytest.raises(InvalidDigest):
            Digest.sha256("ab" * 10)


class TestDigestValue:
    def test_is_frozen(self):
        d = Digest.sha256(_HEX)
        with pytest.raises(Exception):
            d.hexdigest = "x"  # type: ignore[misc]

    def test_equality_by_value(self):
        assert Digest.sha256(_HEX) == Digest.sha256(_HEX)

    def test_differs_across_algorithms(self):
        assert Digest.parse(f"sha256:{_HEX}") != Digest.parse(f"md5:{'a' * 32}")

    def test_hashable(self):
        assert len({Digest.sha256(_HEX), Digest.sha256(_HEX)}) == 1


class TestDigestOfFile:
    def test_matches_hashlib(self, tmp_path):
        p = tmp_path / "blob.bin"
        p.write_bytes(_BODY)
        assert Digest.of_file(p) == Digest.sha256(_HEX)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.bin"
        p.write_bytes(b"")
        assert Digest.of_file(p) == Digest.sha256(hashlib.sha256(b"").hexdigest())

    def test_streams_large_files_without_loading_them_whole(self, tmp_path):
        p = tmp_path / "big.bin"
        payload = b"x" * (4 * 1024 * 1024)
        p.write_bytes(payload)
        assert Digest.of_file(p) == Digest.sha256(hashlib.sha256(payload).hexdigest())


class TestDigestMatches:
    def test_true_on_identical(self):
        assert Digest.sha256(_HEX).matches(Digest.sha256(_HEX))

    def test_false_on_different_hex(self):
        assert not Digest.sha256(_HEX).matches(Digest.sha256("0" * 64))

    def test_false_across_algorithms(self):
        assert not Digest.parse(f"sha256:{_HEX}").matches(Digest.parse(f"md5:{'a' * 32}"))


class TestSha256Stream:
    def test_incremental_equals_one_shot(self):
        stream = Sha256Stream()
        for chunk in (b"molecular", b" ", b"bytes"):
            stream.update(chunk)
        assert stream.digest() == Digest.sha256(_HEX)

    def test_empty_stream(self):
        assert Sha256Stream().digest() == Digest.sha256(hashlib.sha256(b"").hexdigest())

    def test_digest_can_be_read_more_than_once(self):
        stream = Sha256Stream()
        stream.update(_BODY)
        assert stream.digest() == stream.digest()
