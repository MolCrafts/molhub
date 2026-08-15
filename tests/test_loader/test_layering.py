"""Structural constraints on the loader package.

Follows ``tests/test_conveyor/test_layering.py``: deliberately crude
source-text checks whose value is that they are hard to satisfy accidentally
and hard to work around quietly. Two properties are guarded — ac-007's one-way
edge (the loader sits *above* ``dataset/`` and ``conveyor/`` and imports both;
neither may import it back) and the bound on the free-function sanction.

**The sanction is three functions in two modules.** The 2026-08-15 operator
override sanctions ``load_dataset``, ``load_dataset_builder`` and ``prepare``
and nothing else. The first two read a dataset and live in
``loader/__init__.py``; ``prepare`` writes one, and
``.claude/specs/hf-facade-04-streaming-prepare.md`` puts it where the writing
happens — "``materialize.py`` — ``BlockExport`` + the ``prepare`` entry" — beside
the type it delegates to rather than one package up from it. ``molhub/__init__``
re-exports it, so ``from molhub import prepare`` is unchanged; what is pinned
here is that the *definition* is in one place and that place is named.

The package is located by path rather than imported, so a module that has not
landed shows up as a named failure in :class:`TestLoaderPackageIsPresent`
instead of turning this file into a collection error. That is what lets the
layering scan below be answerable today, before the package exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import molhub
import molhub.loader
from molhub.loader import materialize

_PACKAGE_ROOT = Path(molhub.__file__).parent / "loader"
_MODULE_FILES = sorted(_PACKAGE_ROOT.rglob("*.py")) if _PACKAGE_ROOT.is_dir() else []

# The two layers the loader is allowed to depend on, and which may never depend
# on it: semantics (`dataset`) and the block plumbing (`conveyor`).
_BELOW_ROOTS = [
    Path(molhub.__file__).parent / "dataset",
    Path(molhub.__file__).parent / "conveyor",
]
_BELOW_FILES = sorted(path for root in _BELOW_ROOTS for path in root.rglob("*.py"))

# The whole of the free-function sanction, spelled out where a reviewer can see
# it: three names, and nothing else anywhere in the package.
_SANCTIONED_FREE_FUNCTIONS = frozenset({"load_dataset", "load_dataset_builder", "prepare"})

# Which module each sanctioned name is *defined* in. A module absent from this
# table declares no free functions at all — its verbs are methods on its types.
_SANCTIONED_BY_MODULE = {
    "__init__.py": frozenset({"load_dataset", "load_dataset_builder"}),
    "materialize.py": frozenset({"prepare"}),
}

# The distribution root, which re-exports `prepare` and defines nothing.
_ROOT_INIT = Path(molhub.__file__)


def _imported_modules(path: Path) -> set[str]:
    """Every dotted module name imported by *path*, at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _public_free_functions(path: Path) -> set[str]:
    """Module-level ``def`` names in *path* that are not private.

    Only the module body counts: a method is a function on a type, which is the
    shape the design prefers, and a nested helper never reaches a caller.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    }


class TestLoaderPackageIsPresent:
    """Without these, the scans below would pass over an empty file list."""

    def test_the_package_directory_exists(self):
        assert _PACKAGE_ROOT.is_dir(), f"{_PACKAGE_ROOT} is missing"

    def test_the_package_declares_itself(self):
        assert (_PACKAGE_ROOT / "__init__.py").is_file()

    def test_the_naming_module_exists(self):
        assert (_PACKAGE_ROOT / "naming.py").is_file()

    def test_the_info_module_exists(self):
        assert (_PACKAGE_ROOT / "info.py").is_file()

    def test_the_builder_module_exists(self):
        assert (_PACKAGE_ROOT / "builder.py").is_file()

    def test_the_mapstyle_module_exists(self):
        assert (_PACKAGE_ROOT / "mapstyle.py").is_file()


class TestTheLayeringEdgeIsOneWay:
    """ac-007: the façade reads the primitives; no primitive reads the façade."""

    def test_the_layers_below_are_present(self):
        assert _BELOW_FILES, "molhub.dataset / molhub.conveyor were not found"

    @pytest.mark.parametrize("module_file", _BELOW_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
    def test_no_module_below_imports_the_loader(self, module_file):
        offenders = {
            name
            for name in _imported_modules(module_file)
            if name == "molhub.loader" or name.startswith("molhub.loader.")
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"


class TestTheFreeFunctionSanctionIsBounded:
    """Three functions, in two named modules. Everything else is a method."""

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_module_declares_a_free_function_the_sanction_does_not_name(self, module_file):
        allowed = _SANCTIONED_BY_MODULE.get(module_file.name, frozenset())
        declared = _public_free_functions(module_file)
        assert declared <= allowed, (
            f"{module_file.name} declares free functions {sorted(declared - allowed)}; "
            "the loader's types own their verbs"
        )

    def test_the_package_init_declares_the_two_reading_functions(self):
        init = _PACKAGE_ROOT / "__init__.py"
        assert init.is_file(), f"{init} is missing"
        assert _public_free_functions(init) == _SANCTIONED_BY_MODULE["__init__.py"]

    def test_the_export_module_declares_prepare(self):
        """The spec puts the entry beside the type it delegates to."""
        module = _PACKAGE_ROOT / "materialize.py"
        assert module.is_file(), f"{module} is missing"
        assert _public_free_functions(module) == _SANCTIONED_BY_MODULE["materialize.py"]

    def test_the_package_declares_exactly_the_three_sanctioned_functions(self):
        """The sum over the package: no fourth free function anywhere in it."""
        declared = {name for path in _MODULE_FILES for name in _public_free_functions(path)}
        assert declared == set(_SANCTIONED_FREE_FUNCTIONS)

    def test_the_loader_facade_exports_all_three(self):
        """Where they are defined is layering; where they are reached is the API."""
        assert _SANCTIONED_FREE_FUNCTIONS <= set(molhub.loader.__all__)

    def test_the_distribution_root_defines_no_free_function_of_its_own(self):
        """``molhub/__init__`` is the front door, not a place work is written."""
        assert _public_free_functions(_ROOT_INIT) == set()

    def test_the_distribution_root_re_exports_the_one_the_loader_defines(self):
        """``from molhub import prepare`` keeps working — it is the same object."""
        assert molhub.prepare is materialize.prepare
