"""Structural constraints on the transport layer.

These are deliberately crude source-text checks. Their value is that they are
hard to satisfy accidentally and hard to work around quietly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import molhub.sources

_PACKAGE_ROOT = Path(molhub.sources.__file__).parent
# Named for what they are — files of Python source — not for the `Source`
# protocol that lives in them. The two senses collided once already.
_MODULE_FILES = sorted(_PACKAGE_ROOT.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    """Every module name imported by *path*, flattened."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestTransportDoesNotDependOnSemantics:
    """L1 knows about bytes. The moment it imports L3, the layering is gone."""

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_dataset_import(self, module_file):
        offenders = {m for m in _imported_modules(module_file) if m.startswith("molhub.dataset")}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_molpy_import(self, module_file):
        offenders = {
            m for m in _imported_modules(module_file) if m.split(".")[0] in {"molpy", "molrs"}
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"


class TestSelfHostedSourceIsNotSpecialCased:
    """If MolHubSource needed a back door, the driver protocol would be wrong."""

    @pytest.mark.parametrize("module", ["fetcher.py", "source.py"])
    def test_no_scheme_literal_comparison(self, module):
        tree = ast.parse((_PACKAGE_ROOT / module).read_text(encoding="utf-8"))
        literals: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for operand in [node.left, *node.comparators]:
                    if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                        literals.append(operand.value)
            elif isinstance(node, ast.Match):
                literals.extend(
                    case.pattern.value.value
                    for case in node.cases
                    if isinstance(case.pattern, ast.MatchValue)
                    and isinstance(case.pattern.value, ast.Constant)
                    and isinstance(case.pattern.value.value, str)
                )
        assert "molhub" not in literals, f"{module} branches on the molhub scheme"

    def test_fetcher_holds_no_driver_class_reference(self):
        """Selection goes through Drivers; the fetcher names no concrete driver."""
        source = (_PACKAGE_ROOT / "fetcher.py").read_text(encoding="utf-8")
        for concrete in ("MolHubSource", "ZenodoSource", "FigshareSource", "HttpsSource"):
            assert concrete not in source

    def test_self_hosted_driver_satisfies_the_protocol(self):
        from molhub.sources import MolHubSource, Source

        assert isinstance(MolHubSource(), Source)

    def test_every_builtin_driver_satisfies_the_protocol(self):
        from molhub.sources import Source
        from molhub.sources.drivers import Drivers

        drivers = Drivers.builtin()
        for scheme in drivers.schemes():
            assert isinstance(drivers.for_scheme(scheme), Source), scheme
