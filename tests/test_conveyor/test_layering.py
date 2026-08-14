"""Structural constraints on the conveyor package.

Follows ``tests/test_sources/test_layering.py``: deliberately crude source-text
checks whose value is that they are hard to satisfy accidentally and hard to work
around quietly. Three properties are guarded: the conveyor is stdlib plus
``molhub`` — it must stay runnable (and unit-testable) with no torch, no molpy,
and no network stack installed — the block lifecycle has exactly four states,
with no fifth one smuggled in as an enum member or a state-valued string, and
the layering edge runs one way, so nothing under ``molhub.sources`` or
``molhub.dataset`` may import the conveyor back.

The package is located by path rather than imported, so a missing module shows up
as a named failure here instead of a collection error.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import molhub
from molhub.conveyor.ledger import Ledger

if TYPE_CHECKING:  # pragma: no cover - a static proof, never executed
    from molhub.conveyor.transfer import TransferLedger

_PACKAGE_ROOT = Path(molhub.__file__).parent / "conveyor"
# Files of Python source, at any depth under the package.
_MODULE_FILES = sorted(_PACKAGE_ROOT.rglob("*.py")) if _PACKAGE_ROOT.is_dir() else []

# The two layers the conveyor is allowed to depend on, and which may never
# depend on it: bytes (`sources`) and semantics (`dataset`).
_BELOW_ROOTS = [
    Path(molhub.__file__).parent / "sources",
    Path(molhub.__file__).parent / "dataset",
]
_BELOW_FILES = sorted(path for root in _BELOW_ROOTS for path in root.rglob("*.py"))

# Roots the conveyor is allowed to reach for. `molhub` earns its place because
# `BlockId` validates through `Coordinate` and records digest through
# `molhub.sources.digest`; nothing else does.
_ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {"molhub"}

# What must never appear, at module level or inside a function: the science and
# transport stacks (this layer is pure bookkeeping) and `hashlib` — digests go
# through `molhub.sources.digest`, which owns the one hashing rule in the repo.
_FORBIDDEN_ROOTS = frozenset({"torch", "numpy", "molpy", "molrs", "requests", "h5py"})

# The four members of the closed lifecycle, spelled as they are declared.
_LEGAL_STATE_MEMBERS = frozenset({"REMOTE", "DOWNLOADING", "READY", "CONSUMED"})

# Fifth states that have a way of appearing when a stage wants somewhere to put
# a flag. Residency is a pin owned by `04-residency`; "pending" and "failed" are
# already expressible as REMOTE and DOWNLOADING->REMOTE respectively.
_FORBIDDEN_STATE_WORDS = frozenset({"resident", "pending", "failed"})


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _enum_member_names(tree: ast.Module) -> dict[str, set[str]]:
    """Member names of every ``Enum`` subclass in *tree*, keyed by class name.

    Only assignments in the class body count, so methods and annotations-without-
    values are not mistaken for members.
    """
    classes: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {
            base.id if isinstance(base, ast.Name) else base.attr
            for base in node.bases
            if isinstance(base, ast.Name | ast.Attribute)
        }
        if not any(base.endswith(("Enum", "Flag")) for base in bases):
            continue
        members: set[str] = set()
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                targets = statement.targets
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                targets = [statement.target]
            else:
                continue
            members.update(
                target.id
                for target in targets
                if isinstance(target, ast.Name) and not target.id.startswith("_")
            )
        classes[node.name] = members
    return classes


def _string_literals(tree: ast.Module) -> set[str]:
    """Every string literal in *tree* except prose.

    Bare string *statements* — module, class, function and attribute docstrings —
    are excluded, so the word "pending" in an explanatory sentence is not a
    finding. Comments never reach the AST at all. What remains are the strings
    the code actually operates on, which is where a fifth state would have to
    live to do any harm.
    """
    prose = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in prose
    }


def _imported_roots(path: Path) -> set[str]:
    """Every root module name imported by *path*, at any nesting depth.

    ``ast.walk`` visits function and method bodies too, so a lazily imported
    dependency inside a method is caught exactly like a module-level one. A
    relative import can only address this package, so it counts as ``molhub``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                roots.add("molhub")
            elif node.module:
                roots.add(node.module.split(".")[0])
    return roots


def _imported_modules(path: Path) -> set[str]:
    """Every dotted module name imported by *path*, at any nesting depth.

    Unlike :func:`_imported_roots` this keeps the whole path, which is what a
    one-way edge inside ``molhub`` has to be judged on.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
    return names


def _the_ledger_fits_the_transfer_seam(ledger: Ledger) -> TransferLedger:
    """Static proof, checked by ``ty``, that ``-01``'s ledger fits the seam.

    Never called. ``TransferLedger`` is a narrow required-side view of the three
    verbs a transfer needs; if it ever grows a fourth, or ``Ledger`` narrows one
    of the three, this line stops type-checking — which is the whole point of
    writing it down. Mirrors ``tests/test_dataset/test_hub.py``.
    """
    return ledger


class TestConveyorPackageIsPresent:
    """Without these, the scans below would pass over an empty file list."""

    def test_the_package_directory_exists(self):
        assert _PACKAGE_ROOT.is_dir(), f"{_PACKAGE_ROOT} is missing"

    def test_the_package_declares_itself(self):
        assert (_PACKAGE_ROOT / "__init__.py").is_file()

    def test_the_block_module_exists(self):
        assert (_PACKAGE_ROOT / "block.py").is_file()

    def test_the_ledger_module_exists(self):
        assert (_PACKAGE_ROOT / "ledger.py").is_file()

    def test_the_roster_module_exists(self):
        assert (_PACKAGE_ROOT / "roster.py").is_file()

    def test_the_splits_module_exists(self):
        assert (_PACKAGE_ROOT / "splits.py").is_file()

    def test_the_transfer_module_exists(self):
        assert (_PACKAGE_ROOT / "transfer.py").is_file()


class TestTheLayeringEdgeIsOneWay:
    """The conveyor reads bytes and semantics; neither of them may read it back."""

    def test_the_layers_below_are_present(self):
        assert _BELOW_FILES, "molhub.sources / molhub.dataset were not found"

    @pytest.mark.parametrize("module_file", _BELOW_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
    def test_no_module_below_imports_the_conveyor(self, module_file):
        offenders = {
            name
            for name in _imported_modules(module_file)
            if name == "molhub.conveyor" or name.startswith("molhub.conveyor.")
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"


class TestTheConveyorSeamsAcceptTheLandedTypes:
    """A transfer's collaborators are protocols; the real types must still fit."""

    def test_the_ledger_satisfies_the_transfer_seam(self):
        """``-01``'s ``Ledger`` declares nothing and fits by shape, as ``Molhub`` does."""
        from molhub.conveyor.transfer import TransferLedger

        assert issubclass(Ledger, TransferLedger)

    def test_the_transfer_seam_is_exactly_the_three_verbs_it_needs(self):
        """A wider view would rebuild ``-01``'s ledger instead of depending on it."""
        from molhub.conveyor.transfer import TransferLedger

        assert sorted(name for name in vars(TransferLedger) if not name.startswith("_")) == [
            "append",
            "lease",
            "release",
        ]


class TestConveyorDependsOnStdlibAndMolhubOnly:
    """One third-party import here and the ledger stops being unit-testable."""

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_every_import_root_is_stdlib_or_molhub(self, module_file):
        offenders = _imported_roots(module_file) - _ALLOWED_ROOTS
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_science_or_transport_dependency(self, module_file):
        offenders = _imported_roots(module_file) & _FORBIDDEN_ROOTS
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_ad_hoc_hashing(self, module_file):
        """Digests go through ``molhub.sources.digest``, never a local hasher."""
        assert "hashlib" not in _imported_roots(module_file), f"{module_file.name} imports hashlib"


class TestNoFifthBlockState:
    """I5 closes the half-ready hole by making a fifth state unrepresentable.

    ``TestBlockState`` proves the four members and the legality table at runtime;
    these checks close the other door, where a stage that wants somewhere to
    park a flag adds a member or starts comparing against a bare string.
    """

    def test_the_state_enum_declares_exactly_the_four_members(self):
        if not (_PACKAGE_ROOT / "block.py").is_file():
            pytest.skip("block.py has not landed; TestConveyorPackageIsPresent carries the signal")
        classes = _enum_member_names(_parse(_PACKAGE_ROOT / "block.py"))
        assert classes.get("BlockState") == _LEGAL_STATE_MEMBERS

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_enum_member_names_a_fifth_state(self, module_file):
        offenders = {
            f"{class_name}.{member}"
            for class_name, members in _enum_member_names(_parse(module_file)).items()
            for member in members
            if member.lower() in _FORBIDDEN_STATE_WORDS
        }
        assert offenders == set(), f"{module_file.name} declares {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_state_valued_string_literal(self, module_file):
        """A state-valued string is how a fifth state routes around the enum."""
        offenders = {
            literal
            for literal in _string_literals(_parse(module_file))
            if literal.strip().lower() in _FORBIDDEN_STATE_WORDS
        }
        assert offenders == set(), f"{module_file.name} operates on {sorted(offenders)}"
