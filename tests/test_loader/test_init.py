"""Tests for the sanctioned free functions.

Mirrors ``src/molhub/loader/__init__.py``. ``load`` is the one read
entry; ``prepare`` writes blocks. There is no builder on the public surface.

ac-003 is complaint (3) made mechanical: ``split`` is a required keyword, as in
PyTorch and as in ``datasets``' own idiom for a single split, and there is no
dict-of-splits container to return when it is omitted — omitting it is a
:class:`TypeError`, not a different return type.

**The ergonomics wave adds four claims about the same call shape.**

* *Every failure the docstrings name is catchable from ``import molhub``.* A
  ``Raises:`` line is a promise a reader will write ``except`` against; a type
  reachable only through ``molhub.conveyor.errors`` turns that promise into
  ``except Exception``, which catches the bugs too. The list is checked
  mechanically, off the docstrings themselves, so a new ``Raises:`` entry for an
  unexported type fails here rather than in a user's traceback.
* *The refusal for a missing ``split`` names the argument.* The type is
  unchanged (ac-003: a :class:`TypeError`). Discovery is ``molhub info`` or
  ``UnknownSplit``, not a second Python type.
* *``load`` is overloaded on ``streaming``.* One function returns two
  genuinely different things — a map-style dataset and a walk — and the runtime
  already knows which. :func:`typing.get_overloads` is what makes "an editor can
  tell them apart" a property of this repo rather than of a reader's IDE.
* *The signature reads user-first.* ``name, split, revision, streaming,
  disk_budget`` are what a call site actually varies; ``registry`` and ``hub``
  are seams a test or an embedder injects, and they sit last.
"""

from __future__ import annotations

import builtins
import inspect
import re
from collections.abc import Callable, Mapping
from typing import get_overloads

import pytest

import molhub
import molhub.loader
from molhub.conveyor.errors import UnroutableUnitError, UnsupportedRecordError
from molhub.conveyor.splits import SplitProvenanceMismatch
from molhub.dataset.protocol import Dataset
from molhub.loader.errors import SplitTableUnavailable, UnknownSplit
from molhub.loader.mapstyle import UnknownRecordKey
from molhub.loader.naming import AmbiguousRevision
from molhub.loader.streaming import StreamingSplitDataset
from molhub.sources.errors import AllLocatorsFailed

#: Every name the package root re-exports beside the three functions, and the
#: module that defines it. Written out rather than derived from ``__all__``: what
#: is pinned is that *these* names are reachable and are the **same object** as
#: the definition, which a comprehension over ``__all__`` could not say.
#:
#: The two refusals of the reachability wave are in the table for completeness —
#: they are already exported, and a table missing them would read as if only the
#: new ones mattered.
#:
#: ``AllLocatorsFailed`` joins them (re-evaluation, ruling 6): it is what
#: ``load`` raises when every mirror of a published file is down, which
#: is the one failure on this path that is nobody's bug and that a script has a
#: real reason to catch — to retry, to fall back, to report. Reaching it means
#: importing ``molhub.sources.errors``, a transport-layer module this façade
#: exists to hide, so a caller who only has ``import molhub`` writes
#: ``except Exception`` and swallows their own bugs with it.
RE_EXPORTED: Mapping[str, object] = {
    "AllLocatorsFailed": AllLocatorsFailed,
    "AmbiguousRevision": AmbiguousRevision,
    "SplitProvenanceMismatch": SplitProvenanceMismatch,
    "SplitTableUnavailable": SplitTableUnavailable,
    "UnknownRecordKey": UnknownRecordKey,
    "UnknownSplit": UnknownSplit,
    "UnroutableUnitError": UnroutableUnitError,
    "UnsupportedRecordError": UnsupportedRecordError,
}

#: The parameters of ``load``, in the order a reader meets them: what
#: names the data first, what selects it second, and the two injection seams
#: last. Hard-coded, because "user-first" is a decision about order and an
#: assertion derived from the signature would agree with any order at all.
LOAD_DATASET_PARAMETERS: tuple[str, ...] = (
    "name",
    "revision",
    "streaming",
    "disk_budget",
    "registry",
    "hub",
)


def raises_names(function: Callable[..., object]) -> tuple[str, ...]:
    """Every exception type named in *function*'s Google-style ``Raises:`` block.

    Reads the docstring rather than the code, because the docstring is the
    promise: what a reader will write ``except`` against is what they were told
    could be raised, and the two are only the same thing if somebody checks.

    Args:
        function: The documented callable.

    Returns:
        The type names, in the order the docstring lists them.
    """
    documentation = inspect.getdoc(function) or ""
    names: list[str] = []
    inside = False
    for line in documentation.splitlines():
        if line.strip() == "Raises:":
            inside = True
            continue
        if not inside:
            continue
        if line and not line.startswith(" "):
            break
        item = re.match(r"^ {4}(\w+):", line)
        if item:
            names.append(item.group(1))
    return tuple(names)


def catchable(name: str) -> object | None:
    """The class *name* names for a caller who has only ``import molhub``.

    Args:
        name: An exception type name out of a ``Raises:`` block.

    Returns:
        The class, from the builtins every ``except`` clause already reaches or
        from the package root, or ``None`` when neither has it.
    """
    return getattr(builtins, name, None) or getattr(molhub, name, None)


class TestLoadDataset:
    """One name, the whole artifact, no split argument."""

    def test_it_is_reachable_from_the_package_root(self):
        assert callable(molhub.load)

    def test_the_primitive_is_the_dataset_class(self):
        from molhub.dataset import QM9

        assert QM9.__name__ == "QM9"

    def test_package_verbs_are_name_only(self):
        assert callable(molhub.fetch)
        assert callable(molhub.search)
        assert callable(molhub.load)

    def test_it_does_not_take_split(self):
        assert "split" not in inspect.signature(molhub.load).parameters

    def test_it_returns_a_map_style_dataset(self, registry, hub, molhub_home):
        dataset = molhub.load("themol/mbis", registry=registry, hub=hub)
        assert isinstance(dataset, Dataset)

    def test_it_returns_the_whole_artifact(self, registry, hub, molhub_home):
        dataset = molhub.load("themol/mbis", registry=registry, hub=hub)
        assert len(dataset) == 6

    def test_subset_is_how_you_split(self, registry, hub, molhub_home):
        dataset = molhub.load("themol/mbis", registry=registry, hub=hub)
        train = molhub.SubsetDataset(dataset, molhub.assignment(dataset)["train"])
        assert len(train) == 3

    def test_it_takes_revision(self, registry, hub, molhub_home):
        dataset = molhub.load("themol/mbis", revision="1", registry=registry, hub=hub)
        assert len(dataset) == 6


class TestNoDatasetBuilderOnThePublicSurface:
    """Discovery is ``molhub info`` / ``UnknownSplit``, not a second type."""

    def test_the_package_root_does_not_export_a_builder(self):
        assert "load_dataset_builder" not in molhub.__all__
        assert "load_dataset" not in molhub.__all__
        assert "DatasetBuilder" not in molhub.__all__
        assert not hasattr(molhub, "load_dataset_builder")
        assert not hasattr(molhub, "load_dataset")

    def test_the_loader_package_does_not_export_a_builder(self):
        assert "load_dataset_builder" not in molhub.loader.__all__
        assert "DatasetBuilder" not in molhub.loader.__all__

    def test_the_package_root_does_not_export_invented_record_types(self):
        for name in ("Feature", "SplitInfo", "DatasetInfo", "PreparedBlocks"):
            assert name not in molhub.__all__
            assert not hasattr(molhub, name)


class TestNoDatasetDictLikeContainer:
    """ac-003's other half: the container that was not introduced."""

    def test_the_loader_exposes_no_dataset_dict(self):
        assert not hasattr(molhub.loader, "DatasetDict")

    def test_no_exported_name_is_a_container_of_splits(self):
        """A ``*Dict`` export is how a dict-of-splits comes back under a new name."""
        offenders = [name for name in molhub.loader.__all__ if "Dict" in name]
        assert offenders == []

    def test_the_package_exports_the_read_entry(self):
        assert "load" in molhub.loader.__all__


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
    package root beside ``load`` itself. An exception you can only catch
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
        """``load``'s documented failure narrows; it does not change."""
        assert issubclass(molhub.loader.UnknownSplit, KeyError)


class TestReExportedNames:
    """Catchable refusals live on the package root. Record types do not.

    A caller writes ``except molhub.UnknownSplit``. They do not name
    ``Feature``, ``PreparedBlocks``, or ``DatasetInfo``.
    """

    @pytest.mark.parametrize("name", sorted(RE_EXPORTED))
    def test_the_package_root_declares_it(self, name):
        assert name in molhub.__all__

    @pytest.mark.parametrize("name", sorted(RE_EXPORTED))
    def test_it_is_reachable_as_an_attribute(self, name):
        """``__all__`` is what ``from molhub import *`` reads; this is the import."""
        assert hasattr(molhub, name)

    @pytest.mark.parametrize(("name", "defined"), sorted(RE_EXPORTED.items()))
    def test_it_is_the_same_object_the_defining_module_holds(self, name, defined):
        """Two exports of one type, never two types that read alike: a caller
        catching ``molhub.UnroutableUnitError`` has to catch what the conveyor
        actually raised."""
        assert getattr(molhub, name) is defined

    def test_every_exported_name_is_declared(self):
        """``__all__`` is the surface; an attribute missing from it is not exported."""
        assert set(RE_EXPORTED) <= set(molhub.__all__)


class TestDocumentedFailuresAreCatchable:
    """Every type a public docstring promises is one ``import molhub`` reaches.

    Mechanical rather than a list: the promise lives in the ``Raises:`` blocks of
    the three sanctioned functions, so that is what is read. A future ``Raises:``
    line for a type nobody exported fails here, at the moment the promise is
    made, instead of when a reader writes ``except`` against it and gets
    ``NameError``.
    """

    #: The sanctioned public functions — the whole of what has to be catchable.
    FUNCTIONS: Mapping[str, Callable[..., object]] = {
        "load": molhub.load,
        "prepare": molhub.prepare,
    }

    @pytest.mark.parametrize("function", sorted(FUNCTIONS))
    def test_every_documented_failure_is_reachable_from_the_package_root(self, function):
        documented = raises_names(self.FUNCTIONS[function])
        unreachable = [name for name in documented if catchable(name) is None]
        assert unreachable == [], (
            f"{function}() documents {unreachable}, which a caller holding only "
            "`import molhub` cannot name — so they would catch Exception instead"
        )

    @pytest.mark.parametrize("function", sorted(FUNCTIONS))
    def test_every_documented_failure_is_an_exception_type(self, function):
        documented = raises_names(self.FUNCTIONS[function])
        wrong = [
            name
            for name in documented
            if not isinstance(catchable(name), type)
            or not issubclass(catchable(name), BaseException)
        ]
        assert wrong == []

    def test_the_reading_function_documents_its_failures_at_all(self):
        """Guards the two tests above from passing over an empty list."""
        assert len(raises_names(molhub.load)) >= 4


class TestLoadDatasetOverloads:
    """One function, two return types, and a runtime record of which is which.

    ``streaming=`` does not change what is loaded — the same name, the same
    split — it changes *how it comes back*: map-style, addressable by index, or a
    walk that keeps one file on disk. A single annotation covering both is
    ``Dataset | IterableDataset``, which makes every call site look like it might
    be either, and makes ``ds[0]`` an editor error on the map-style path where it
    is the whole point.

    :func:`typing.get_overloads` is the observable: the ``@overload`` stubs are
    registered at import, so "this function is overloaded" is a fact about the
    module rather than a claim about someone's IDE.
    """

    def test_it_declares_overloads(self):
        assert len(get_overloads(molhub.loader.load)) >= 2

    def test_the_root_export_carries_the_same_overloads(self):
        """The re-export is the same object, so the registry lookup finds them."""
        assert get_overloads(molhub.load) == get_overloads(molhub.loader.load)

    def test_the_overloads_discriminate_on_the_streaming_literal(self):
        """Both literals appear, or the overloads do not distinguish anything."""
        declared = [
            str(overload.__annotations__.get("streaming", ""))
            for overload in get_overloads(molhub.loader.load)
        ]
        assert any("True" in annotation for annotation in declared), declared
        assert any("False" in annotation for annotation in declared), declared

    def test_one_overload_returns_the_walk(self):
        returned = [
            str(overload.__annotations__.get("return", ""))
            for overload in get_overloads(molhub.loader.load)
        ]
        assert any("StreamingSplitDataset" in annotation for annotation in returned), returned

    def test_another_overload_returns_the_map_style_dataset(self):
        returned = [
            str(overload.__annotations__.get("return", ""))
            for overload in get_overloads(molhub.loader.load)
        ]
        assert any(
            "Dataset" in annotation and "StreamingSplitDataset" not in annotation
            for annotation in returned
        ), returned

    def test_the_runtime_behaviour_is_unchanged_without_streaming(self, registry, hub, molhub_home):
        """An overload is a type-level statement; the call it describes still runs."""
        dataset = molhub.load("themol/mbis", streaming=False, registry=registry, hub=hub)
        assert isinstance(dataset, Dataset)

    def test_the_runtime_behaviour_is_unchanged_with_streaming(
        self, verified_registry, landing_hub
    ):
        walk = molhub.load(
            "themol/mbis",
            streaming=True,
            registry=verified_registry,
            hub=landing_hub,
        )
        assert isinstance(walk, StreamingSplitDataset)


class TestUserFirstSignatures:
    """What a call site varies comes first; the injection seams come last.

    ``registry=`` and ``hub=`` exist so a test — and an embedder with its own
    registry — can supply them, and essentially no user call passes either. They
    were sitting in the middle of both signatures, between ``revision`` and the
    two arguments a streaming caller actually reaches for, so ``--help``-style
    introspection and every rendered signature in the docs put the plumbing
    before the product. Keyword-only throughout, so the order is documentation
    rather than an ABI: moving them breaks nobody's call and fixes everybody's
    reading.
    """

    def test_load_dataset_reads_user_first(self):
        assert tuple(inspect.signature(molhub.load).parameters) == LOAD_DATASET_PARAMETERS

    def test_load_dataset_takes_the_name_positionally_and_nothing_else(self):
        parameters = inspect.signature(molhub.load).parameters
        assert parameters["name"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert all(
            parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            for name in LOAD_DATASET_PARAMETERS[1:]
        )

    def test_load_dataset_puts_the_seams_last(self):
        """The claim in isolation, so a reordering that only moves ``streaming``
        still reports the part it did not fix."""
        ordered = tuple(inspect.signature(molhub.load).parameters)
        assert ordered[-2:] == ("registry", "hub")
