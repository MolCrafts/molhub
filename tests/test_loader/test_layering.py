"""Structural constraints on the loader package.

Follows ``tests/test_conveyor/test_layering.py``: deliberately crude
source-text checks whose value is that they are hard to satisfy accidentally
and hard to work around quietly. Two properties are guarded — ac-007's one-way
edge (the loader sits *above* ``dataset/`` and ``conveyor/`` and imports both;
neither may import it back) and the bound on the free-function sanction (the
façade's two functions live in ``loader/__init__.py`` and nowhere else).

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
# it: two names, in one module, and nothing else anywhere in the package.
_SANCTIONED_FREE_FUNCTIONS = frozenset({"load_dataset", "load_dataset_builder"})


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
    """Two functions, in one module. Everything else is a method on a type."""

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_only_the_package_init_declares_free_functions(self, module_file):
        if module_file.name == "__init__.py":
            pytest.skip("__init__.py owns the two sanctioned free functions")
        assert _public_free_functions(module_file) == set(), (
            f"{module_file.name} declares free functions "
            f"{sorted(_public_free_functions(module_file))}; the loader's types own their verbs"
        )

    def test_the_package_init_declares_exactly_the_two_sanctioned_functions(self):
        init = _PACKAGE_ROOT / "__init__.py"
        assert init.is_file(), f"{init} is missing"
        assert _public_free_functions(init) == _SANCTIONED_FREE_FUNCTIONS
