"""Structural constraints on the transport layer.

These are deliberately crude source-text checks. Their value is that they are
hard to satisfy accidentally and hard to work around quietly.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import molhub.registry

_PACKAGE_ROOT = Path(molhub.registry.__file__).parent
_SOURCES = sorted(_PACKAGE_ROOT.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    """Every module name imported by *path*, flattened."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestTransportDoesNotDependOnSemantics:
    """L1 knows about bytes. The moment it imports L3, the layering is gone."""

    @pytest.mark.parametrize("source", _SOURCES, ids=lambda p: p.name)
    def test_no_dataset_import(self, source):
        offenders = {m for m in _imported_modules(source) if m.startswith("molhub.dataset")}
        assert offenders == set(), f"{source.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("source", _SOURCES, ids=lambda p: p.name)
    def test_no_molpy_import(self, source):
        offenders = {m for m in _imported_modules(source) if m.split(".")[0] in {"molpy", "molrs"}}
        assert offenders == set(), f"{source.name} imports {sorted(offenders)}"


class TestSelfHostedRegistryIsNotSpecialCased:
    """If MolHubRegistry needed a back door, the driver protocol would be wrong."""

    @pytest.mark.parametrize("module", ["fetcher.py", "driver.py"])
    def test_no_scheme_literal_comparison(self, module):
        source = (_PACKAGE_ROOT / module).read_text()
        tree = ast.parse(source)
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
        source = (_PACKAGE_ROOT / "fetcher.py").read_text()
        for concrete in ("MolHubRegistry", "ZenodoRegistry", "FigshareRegistry", "HttpsRegistry"):
            assert concrete not in source

    def test_self_hosted_driver_satisfies_the_protocol(self):
        from molhub.registry import MolHubRegistry, Registry

        assert isinstance(MolHubRegistry(), Registry)

    def test_every_builtin_driver_satisfies_the_protocol(self):
        from molhub.registry import Registry
        from molhub.registry.drivers import Drivers

        drivers = Drivers.builtin()
        for scheme in drivers.schemes():
            assert isinstance(drivers.for_scheme(scheme), Registry), scheme
