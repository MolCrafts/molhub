"""Structural constraints on the conveyor package.

Follows ``tests/test_sources/test_layering.py``: deliberately crude source-text
checks whose value is that they are hard to satisfy accidentally and hard to work
around quietly. Four properties are guarded: the import surface each module is
allowed (below), the block lifecycle has exactly four states with no fifth one
smuggled in as an enum member or a state-valued string, the layering edge runs
one way so nothing under ``molhub.sources`` or ``molhub.dataset`` may import the
conveyor back, and ``pyproject.toml`` actually declares what the package
imports.

**The import rule is now per module, superseding ``-01``'s package-wide one.**
``-01-ledger`` could say "stdlib plus ``molhub``, at any depth, everywhere",
because bookkeeping is all the package did. The prepare stage's job is to turn
molecular records into numeric columns and hand them to molnex, so
``-03-prepare`` (spec sections 3, 5, 6) splits the rule three ways, matching
``-04-residency``'s ac-012 formulation:

* ``block.py`` / ``ledger.py`` / ``roster.py`` / ``splits.py`` / ``transfer.py``
  (and ``-04``'s ``tier.py`` / ``backpressure.py`` / ``coverage.py``) keep the
  original rule *exactly*: stdlib + ``molhub``, no numpy, no torch, no molix, at
  any depth. This is the layer that must stay importable in a shell with nothing
  installed;
* ``encoder.py`` and ``prepare.py`` may import ``numpy`` at module level — numpy
  becomes a declared base dependency in this spec, which
  :class:`TestPyprojectDeclaresWhatTheConveyorImports` pins;
* ``prepare.py`` alone may reach ``torch`` / ``molix``, and only from inside a
  function or method (the Option-A lazy import in ``MolnexBlockWriter``). No
  module of the package may import them at module scope, ever — that is what
  keeps ``import molhub.conveyor.prepare`` working in a torch-free base install.

A module not named in the tables below gets the strict bookkeeping rule, so a
new file stays locked down until someone writes down why it should not be.

"Module scope" here means *executed at import time*: module body, class bodies,
and ``if`` / ``try`` blocks around them, but not function or method bodies. A
``if TYPE_CHECKING:`` import of ``molix`` is therefore a finding too. That is
deliberate — the guard is meant to be crude, and the seam is typed through
protocols, not through molnex's own names.

The package is located by path rather than imported, so a missing module shows up
as a named failure here instead of a collection error.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
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

# The repo root, where `pyproject.toml` declares what any of this may import.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Roots every module may reach for. `molhub` earns its place because
# `BlockId` validates through `Coordinate` and records digest through
# `molhub.sources.digest`; nothing else does.
_ALLOWED_ROOTS = frozenset(sys.stdlib_module_names) | {"molhub"}

# What must never appear, at module level or inside a function, unless the
# per-module table below widens it: the science and transport stacks (the
# bookkeeping layer is pure bookkeeping).
_FORBIDDEN_ROOTS = frozenset({"torch", "molix", "numpy", "molpy", "molrs", "requests", "h5py"})

# Never importable at *module scope*, in any module of the package — the whole
# point of the Option-A ruling. `molrs` is on the list because molnex-adjacent
# code must speak `molpy`, never the Rust core directly.
_NO_MODULE_SCOPE_ROOTS = frozenset({"torch", "molix", "molrs"})

# Modules that may import numpy — the two that hold numeric columns.
_NUMPY_MODULES = frozenset({"encoder.py", "prepare.py"})

# `-04-residency`'s three modules, named here so their strict rule is a written
# fact rather than a default nobody checked. They are bookkeeping —  byte
# budgets, a queue, a fold over records and a JSON read — so they keep `-01`'s
# package-wide surface exactly: stdlib + `molhub`, at any depth. ac-012 turns on
# this: `ReadyBlocks` reads molnex's `manifest.json` as JSON precisely so the
# sampler handoff never pulls torch into a data-plane repo.
_RESIDENCY_MODULES = frozenset({"tier.py", "backpressure.py", "coverage.py"})

# Modules that may reach torch / molix at all, and then only inside a function.
_LAZY_MOLNEX_MODULES = frozenset({"prepare.py"})

# Modules exempt from the no-`hashlib` rule; see
# `TestIdentityHashingIsScopedToTheEncoder` for why there is exactly one.
_HASHING_MODULES = frozenset({"encoder.py"})

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


def _module_level_imported_roots(path: Path) -> set[str]:
    """Every root module name *path* imports at import time.

    Recurses into class bodies and into ``if`` / ``try`` blocks — those run when
    the module is imported — but stops at every function, method and lambda, so
    a lazy import inside ``MolnexBlockWriter.__init__`` is invisible here and a
    ``if TYPE_CHECKING:`` import is not.
    """
    roots: set[str] = set()

    def walk(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue
            if isinstance(child, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in child.names)
            elif isinstance(child, ast.ImportFrom):
                roots.add("molhub" if child.level else (child.module or "").split(".")[0])
            walk(child)

    walk(ast.parse(path.read_text(encoding="utf-8")))
    return roots - {""}


def _allowed_roots(module_file: Path) -> frozenset[str]:
    """The import surface *module_file* is allowed, at any depth."""
    allowed = set(_ALLOWED_ROOTS)
    if module_file.name in _NUMPY_MODULES:
        allowed.add("numpy")
    if module_file.name in _LAZY_MOLNEX_MODULES:
        allowed |= {"torch", "molix"}
    return frozenset(allowed)


def _requirement_name(requirement: str) -> str:
    """The distribution name of a PEP 508 requirement string, normalized."""
    name = re.split(r"[\s<>=!~;\[]", requirement.strip(), maxsplit=1)[0]
    return name.lower().replace("_", "-")


def _pyproject() -> dict[str, object]:
    """The repo's ``pyproject.toml``, parsed with stdlib ``tomllib``."""
    return tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


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

    def test_the_errors_module_exists(self):
        assert (_PACKAGE_ROOT / "errors.py").is_file()

    def test_the_encoder_module_exists(self):
        assert (_PACKAGE_ROOT / "encoder.py").is_file()

    def test_the_prepare_module_exists(self):
        assert (_PACKAGE_ROOT / "prepare.py").is_file()

    def test_the_tier_module_exists(self):
        assert (_PACKAGE_ROOT / "tier.py").is_file()

    def test_the_backpressure_module_exists(self):
        assert (_PACKAGE_ROOT / "backpressure.py").is_file()

    def test_the_coverage_module_exists(self):
        assert (_PACKAGE_ROOT / "coverage.py").is_file()


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

    def test_the_ledger_satisfies_the_tier_seam(self):
        """``test_tier.py`` drives a fake; this is where the real one must still fit."""
        from molhub.conveyor.tier import BlockLedger

        assert issubclass(Ledger, BlockLedger)

    def test_the_tier_seam_is_exactly_the_three_verbs_it_needs(self):
        """State, live leases, one append. A fourth verb would be a second ledger."""
        from molhub.conveyor.tier import BlockLedger

        assert sorted(name for name in vars(BlockLedger) if not name.startswith("_")) == [
            "active_leases",
            "append",
            "replay",
        ]


class TestConveyorImportsAreDeclaredPerModule:
    """One undeclared import here and a layer stops being unit-testable.

    The bookkeeping modules keep ``-01``'s package-wide rule; ``encoder.py`` and
    ``prepare.py`` get exactly the widening the prepare spec argues for, and
    nothing beyond it. The tables live at the top of this file, so widening the
    rule for a new module is a visible edit rather than a quiet one.
    """

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_every_import_root_is_allowed_for_that_module(self, module_file):
        offenders = _imported_roots(module_file) - _allowed_roots(module_file)
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_science_or_transport_dependency(self, module_file):
        offenders = _imported_roots(module_file) & (_FORBIDDEN_ROOTS - _allowed_roots(module_file))
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_the_bookkeeping_layer_stays_numeric_free(self, module_file):
        """numpy is a *columns* dependency; the ledger layer has no columns."""
        if module_file.name in _NUMPY_MODULES:
            pytest.skip(f"{module_file.name} holds numeric columns and may import numpy")
        assert "numpy" not in _imported_roots(module_file), f"{module_file.name} imports numpy"

    @pytest.mark.parametrize("name", sorted(_RESIDENCY_MODULES))
    def test_the_residency_modules_are_not_widened(self, name):
        """The tables, not the files: a widening for these three is a visible edit."""
        assert _allowed_roots(_PACKAGE_ROOT / name) == _ALLOWED_ROOTS

    @pytest.mark.parametrize("name", sorted(_RESIDENCY_MODULES))
    def test_the_residency_modules_import_only_stdlib_and_molhub(self, name):
        """ac-012, at any depth: no torch, no molix, no molrs, and no numpy either."""
        module_file = _PACKAGE_ROOT / name
        assert module_file.is_file(), f"{name} has not landed"
        assert _imported_roots(module_file) <= _ALLOWED_ROOTS

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_no_ad_hoc_hashing(self, module_file):
        """Digests go through ``molhub.sources.digest``, never a local hasher."""
        if module_file.name in _HASHING_MODULES:
            pytest.skip(
                f"{module_file.name} owns the scoped blake2b-128 identity exception; "
                "TestIdentityHashingIsScopedToTheEncoder carries that signal"
            )
        assert "hashlib" not in _imported_roots(module_file), f"{module_file.name} imports hashlib"


class TestNoModuleScopeTorchOrMolnex:
    """The Option-A ruling, checked where it can be checked: the source text.

    ``python -c "import molhub.conveyor.prepare"`` must succeed in an install
    with neither torch nor molnex, so ``from molix.store.block import
    BlockWriter, SamplingUnit`` may appear in exactly one place — inside
    ``MolnexBlockWriter``'s body. Anywhere that runs at import time, including a
    ``if TYPE_CHECKING:`` block, is a finding.
    """

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_nothing_imports_torch_or_molix_at_import_time(self, module_file):
        offenders = _module_level_imported_roots(module_file) & _NO_MODULE_SCOPE_ROOTS
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)} at module scope"

    @pytest.mark.parametrize("module_file", _MODULE_FILES, ids=lambda p: p.name)
    def test_only_the_adapter_module_reaches_molnex_at_all(self, module_file):
        """One import site, named in the spec — not one per collaborator."""
        if module_file.name in _LAZY_MOLNEX_MODULES:
            pytest.skip(f"{module_file.name} owns the single lazy molnex import site")
        offenders = _imported_roots(module_file) & {"torch", "molix"}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"


class TestIdentityHashingIsScopedToTheEncoder:
    """One scoped exception to the repo's no-local-hasher rule, and its bounds.

    ``molhub.sources.digest.Digest`` owns "an algorithm plus a hex string" for
    *catalogued bytes*: sha256 over a file, compared against a manifest. Molecular
    identity is a different function — blake2b-128 over a ``mapped_isomeric_smiles``
    string, with no file, no manifest and no ``Digest`` wrapper — and it must stay
    bit-identical to the rule that produced the shipped ``class1-universal-splits@1``
    tables, which is why the prepare spec promotes it into ``encoder.py`` instead
    of leaving a second copy in ``scripts/build_class1_splits.py``.

    So ``encoder.py`` may import ``hashlib``; every other module may not, and
    ``encoder.py`` may use it for ``blake2b`` and nothing else. A sha256 that
    appeared here would be a content digest routing around ``Digest``.
    """

    @staticmethod
    def _hashlib_names(path: Path) -> set[str]:
        """Every ``hashlib`` constructor *path* names, however it was imported."""
        tree = _parse(path)
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "hashlib"
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "hashlib":
                used |= {alias.name for alias in node.names}
        return used

    def test_the_encoder_hashes_with_blake2b_and_nothing_else(self):
        if not (_PACKAGE_ROOT / "encoder.py").is_file():
            pytest.skip(
                "encoder.py has not landed; TestConveyorPackageIsPresent carries the signal"
            )
        assert self._hashlib_names(_PACKAGE_ROOT / "encoder.py") <= {"blake2b"}

    def test_no_other_module_hashes_at_all(self):
        offenders = {
            module_file.name
            for module_file in _MODULE_FILES
            if module_file.name not in _HASHING_MODULES and self._hashlib_names(module_file)
        }
        assert offenders == set(), f"{sorted(offenders)} hash outside molhub.sources.digest"


class TestPyprojectDeclaresWhatTheConveyorImports:
    """An import that no dependency group declares is a dependency defect.

    ``numpy`` is imported at module scope by ten modules under ``src/molhub/``
    and declared nowhere; it resolves today only through h5py's transitive pull.
    The prepare stage makes it load-bearing on a new path, so the declaration
    lands with this spec and is pinned here so the regression cannot return.
    """

    def test_pyproject_is_where_this_test_expects_it(self):
        assert (_REPO_ROOT / "pyproject.toml").is_file(), _REPO_ROOT

    def test_numpy_is_declared_as_a_base_dependency(self):
        project = _pyproject()["project"]
        assert isinstance(project, dict)
        declared = {_requirement_name(str(item)) for item in project["dependencies"]}
        assert "numpy" in declared, f"declared: {sorted(declared)}"

    def test_the_prepare_extra_is_declared(self):
        """molnex is not on PyPI, so the extra names the publishable half only."""
        project = _pyproject()["project"]
        assert isinstance(project, dict)
        extras = project["optional-dependencies"]
        assert isinstance(extras, dict)
        assert "prepare" in extras, f"declared extras: {sorted(extras)}"


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
