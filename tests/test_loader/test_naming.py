"""Tests for HF-shaped name resolution.

Mirrors ``src/molhub/loader/naming.py``. Every test resolves against a real
:class:`~molhub.registry.Registry` loaded from a ``tmp_path`` directory of YAML
manifests — the registry is cheap enough over a directory that a stand-in with
the same three methods would only prove the stand-in.

Two shapes the spec leaves implicit are picked here, because a test cannot call
them without picking one:

* :class:`~molhub.loader.naming.DatasetName` takes the revision as a keyword —
  ``DatasetName("themol/mbis", revision="1")`` — matching the ``revision=``
  keyword the builder and ``load_dataset`` take, and ``resolve(registry)``
  returns a :class:`~molhub.coordinate.Coordinate` rather than its string form,
  since ``DatasetInfo.coordinate`` echoes the resolved object.
* The ambiguous-ordering refusal is ``AmbiguousRevision``. The spec states the
  behaviour ("refuses and demands an explicit ``revision=``") and ac-001 states
  the message ("naming the available revisions"); the type is the one thing
  neither states, and a test cannot write ``pytest.raises`` without a name.
"""

from __future__ import annotations

import pytest

from molhub.coordinate import Coordinate
from molhub.loader.naming import AmbiguousRevision, DatasetName

from .conftest import build_registry


class TestDatasetName:
    """``themol/mbis`` in, one pinned coordinate out — or a refusal."""

    def test_a_shorthand_name_resolves_to_a_pinned_coordinate(self, tmp_path):
        """ac-001: the HF spelling names an artifact; the coordinate names a version."""
        registry = build_registry(tmp_path / "registry")
        assert DatasetName("themol/mbis").resolve(registry) == Coordinate.parse(
            "dataset:themol/mbis@1"
        )

    def test_the_resolved_coordinate_renders_canonically(self, tmp_path):
        """What a run records is the full form, never the shorthand it was typed as."""
        registry = build_registry(tmp_path / "registry")
        assert DatasetName("themol/mbis").resolve(registry).canonical == "dataset:themol/mbis@1"

    def test_a_name_without_a_namespace_takes_the_default_one(self, tmp_path):
        """``qm9`` is ``molcrafts/qm9``, exactly as ``Coordinate.parse`` reads it."""
        registry = build_registry(
            tmp_path / "registry", versions=("v2",), namespace="molcrafts", name="qm9"
        )
        assert DatasetName("qm9").resolve(registry).canonical == "dataset:molcrafts/qm9@v2"

    def test_an_explicit_revision_is_honoured(self, tmp_path):
        registry = build_registry(tmp_path / "registry", versions=("1", "2"))
        assert DatasetName("themol/mbis", revision="1").resolve(registry).version == "1"

    def test_the_newest_declared_version_is_the_default(self, tmp_path):
        registry = build_registry(tmp_path / "registry", versions=("1", "2"))
        assert DatasetName("themol/mbis").resolve(registry).version == "2"

    def test_the_default_orders_versions_numerically_not_lexically(self, tmp_path):
        """A lexical sort answers ``2`` here, which is what "numeric-aware" excludes."""
        registry = build_registry(tmp_path / "registry", versions=("2", "10"))
        assert DatasetName("themol/mbis").resolve(registry).version == "10"

    def test_versions_that_do_not_order_are_refused(self, tmp_path):
        """A silently-picked version breaks the promise that a locator pins one."""
        registry = build_registry(tmp_path / "registry", versions=("v2", "beta"))
        with pytest.raises(AmbiguousRevision):
            DatasetName("themol/mbis").resolve(registry)

    def test_the_refusal_names_every_available_revision(self, tmp_path):
        """ac-001: the only useful next step is to type one of them, so list them."""
        registry = build_registry(tmp_path / "registry", versions=("v2", "beta"))
        with pytest.raises(AmbiguousRevision) as raised:
            DatasetName("themol/mbis").resolve(registry)
        message = str(raised.value)
        assert "v2" in message and "beta" in message

    def test_an_explicit_revision_resolves_what_ordering_cannot(self, tmp_path):
        """The refusal demands a ``revision=``; giving one has to actually work."""
        registry = build_registry(tmp_path / "registry", versions=("v2", "beta"))
        assert DatasetName("themol/mbis", revision="beta").resolve(registry).version == "beta"
