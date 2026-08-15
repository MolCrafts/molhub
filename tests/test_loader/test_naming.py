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
from molhub.registry import UnknownArtifact

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


class TestAnUnknownNameIsRefusedAsANameProblem:
    """A typo in the *name* is not a question about revisions.

    The default-revision lookup is where a name nobody declares is first noticed
    — ``registry.versions()`` comes back empty — and the refusal was written from
    that vantage point: *"...so there is no revision to default to"*. The reader
    typed ``load_dataset("themol/mbsi", split="train")``; they do not have a
    revision problem, they have a spelling problem, and the sentence sends them
    to look for versions of a dataset that does not exist.

    What it should do instead is what a reader can act on: lead with the name
    that missed, and name the verb that lists the ones that did not. The
    namespace hint below is the same refusal's other half and must survive the
    rewrite — it is the one case where molhub knows exactly what the user meant.

    The revision *ordering* refusal is a different sentence about a real revision
    problem, and it is pinned unchanged in :class:`TestDatasetName` above; the
    contrast is checked here so "drop the word revision" cannot be applied to
    both.
    """

    @pytest.fixture
    def registry(self, tmp_path):
        """A registry declaring ``dataset:themol/mbis@1`` and nothing else."""
        return build_registry(tmp_path / "registry")

    def test_it_is_still_the_registrys_own_refusal(self, registry):
        """The type does not move: callers already catch ``UnknownArtifact``."""
        with pytest.raises(UnknownArtifact):
            DatasetName("themol/mbsi").resolve(registry)

    def test_the_refusal_leads_with_the_name_that_missed(self, registry):
        with pytest.raises(UnknownArtifact) as raised:
            DatasetName("themol/mbsi").resolve(registry)
        assert str(raised.value).startswith("dataset:themol/mbsi"), str(raised.value)

    def test_the_refusal_names_the_verb_that_lists_the_declared_ones(self, registry):
        """Which datasets *are* there is one command away, and this is the
        moment the reader wants it."""
        with pytest.raises(UnknownArtifact) as raised:
            DatasetName("themol/mbsi").resolve(registry)
        assert "molhub search" in str(raised.value), str(raised.value)

    def test_the_refusal_does_not_blame_the_revision_default(self, registry):
        """The sentence this replaces, quoted so its return is loud."""
        with pytest.raises(UnknownArtifact) as raised:
            DatasetName("themol/mbsi").resolve(registry)
        assert "no revision to default to" not in str(raised.value)

    def test_the_refusal_does_not_mention_revisions_at_all(self, registry):
        """There is no revision to discuss: nothing of this name is published."""
        with pytest.raises(UnknownArtifact) as raised:
            DatasetName("themol/mbsi").resolve(registry)
        assert "revision" not in str(raised.value).lower(), str(raised.value)

    def test_a_bare_namespace_still_hands_over_the_names_under_it(self, registry):
        """The half of this refusal that already worked, pinned against the rewrite."""
        with pytest.raises(UnknownArtifact) as raised:
            DatasetName("themol").resolve(registry)
        assert "themol/mbis" in str(raised.value), str(raised.value)

    def test_the_unorderable_revision_refusal_still_talks_about_revisions(self, tmp_path):
        """The contrast: that one *is* a revision problem, and says so."""
        registry = build_registry(tmp_path / "unorderable", versions=("v2", "beta"))
        with pytest.raises(AmbiguousRevision) as raised:
            DatasetName("themol/mbis").resolve(registry)
        assert "revision" in str(raised.value).lower()
