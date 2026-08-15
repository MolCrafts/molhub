"""Tests for the two sanctioned free functions.

Mirrors ``src/molhub/loader/__init__.py``. ``load_dataset`` and
``load_dataset_builder`` are the whole of the façade's function surface and the
only free functions the scoped operator override permits anywhere in molhub;
they are thin delegations to :class:`~molhub.loader.builder.DatasetBuilder`, so
what is pinned here is the *call shape*, not a second copy of the builder's
behaviour.

ac-003 is complaint (3) made mechanical: ``split`` is a required keyword, as in
PyTorch and as in ``datasets``' own idiom for a single split, and there is no
dict-of-splits container to return when it is omitted — omitting it is a
:class:`TypeError`, not a different return type.
"""

from __future__ import annotations

import pytest

import molhub
import molhub.loader
from molhub.dataset.protocol import Dataset
from molhub.loader.builder import DatasetBuilder


class TestLoadDataset:
    """One name, one split, one map-style dataset."""

    def test_it_is_reachable_from_the_package_root(self):
        assert callable(molhub.load_dataset)

    def test_omitting_split_is_a_type_error(self):
        """Not a dict of splits, not a default of ``"train"`` — a missing argument."""
        with pytest.raises(TypeError):
            molhub.load_dataset("themol/mbis")

    def test_split_is_keyword_only(self, registry, hub, molhub_home):
        """``load_dataset(name, "train")`` would make position 2 a second syntax."""
        with pytest.raises(TypeError):
            molhub.load_dataset("themol/mbis", "train", registry=registry, hub=hub)

    def test_it_returns_a_map_style_dataset(self, registry, hub, molhub_home):
        dataset = molhub.load_dataset("themol/mbis", split="train", registry=registry, hub=hub)
        assert isinstance(dataset, Dataset)

    def test_it_returns_the_split_that_was_asked_for(self, registry, hub, molhub_home):
        dataset = molhub.load_dataset("themol/mbis", split="val", registry=registry, hub=hub)
        assert len(dataset) == 2

    def test_it_takes_the_revision_the_builder_takes(self, registry, hub, molhub_home):
        dataset = molhub.load_dataset(
            "themol/mbis", split="train", revision="1", registry=registry, hub=hub
        )
        assert len(dataset) == 3


class TestLoadDatasetBuilder:
    """The discovery half: describe the dataset, download nothing."""

    def test_it_is_reachable_from_the_package_root(self):
        assert callable(molhub.load_dataset_builder)

    def test_it_returns_a_builder(self, registry, hub, molhub_home):
        builder = molhub.load_dataset_builder("themol/mbis", registry=registry, hub=hub)
        assert isinstance(builder, DatasetBuilder)

    def test_the_builder_it_returns_describes_the_resolved_artifact(
        self, registry, hub, molhub_home
    ):
        builder = molhub.load_dataset_builder("themol/mbis", registry=registry, hub=hub)
        assert builder.info.coordinate.canonical == "dataset:themol/mbis@1"


class TestNoDatasetDictLikeContainer:
    """ac-003's other half: the container that was not introduced."""

    def test_the_loader_exposes_no_dataset_dict(self):
        assert not hasattr(molhub.loader, "DatasetDict")

    def test_no_exported_name_is_a_container_of_splits(self):
        """A ``*Dict`` export is how a dict-of-splits comes back under a new name."""
        offenders = [name for name in molhub.loader.__all__ if "Dict" in name]
        assert offenders == []

    def test_the_package_exports_the_two_free_functions(self):
        assert {"load_dataset", "load_dataset_builder"} <= set(molhub.loader.__all__)


class TestRefusalExports:
    """The two refusals a caller has to be able to name, exported where they look.

    A reachability wave adds two typed failures to this layer:

    * ``SplitTableUnavailable`` — the published split derivation is not on this
      machine, and no download produces it: it is *built*, by a generator that
      now ships inside the wheel.
    * ``UnknownSplit`` — the split name is not one this dataset declares, decided
      before anything is fetched.

    Both are things a script legitimately catches — one to run the generator, the
    other to print the declared names — so both have to be importable from the
    same two places every other loader type is: :mod:`molhub.loader`, and the
    package root beside ``load_dataset`` itself. An exception you can only catch
    by importing a private module is one callers catch as ``Exception``.
    """

    def test_the_loader_exports_the_absent_split_table_refusal(self):
        assert "SplitTableUnavailable" in molhub.loader.__all__

    def test_the_package_root_exports_the_absent_split_table_refusal(self):
        assert "SplitTableUnavailable" in molhub.__all__

    def test_both_spellings_are_the_same_class(self):
        """Two exports of one type, never two types that read alike."""
        assert molhub.SplitTableUnavailable is molhub.loader.SplitTableUnavailable

    def test_the_loader_exports_the_unknown_split_refusal(self):
        assert "UnknownSplit" in molhub.loader.__all__

    def test_the_package_root_exports_the_unknown_split_refusal(self):
        assert "UnknownSplit" in molhub.__all__

    def test_both_spellings_of_the_unknown_split_are_the_same_class(self):
        assert molhub.UnknownSplit is molhub.loader.UnknownSplit

    def test_an_unknown_split_is_still_a_key_error(self):
        """``load_dataset``'s documented failure narrows; it does not change."""
        assert issubclass(molhub.loader.UnknownSplit, KeyError)
