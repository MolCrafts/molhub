"""Tests for the publication audit — what the wheel is required to carry.

Mirrors ``scripts/check_package_contents.py``, the repo-root audit that builds
the wheel and the npm tarball in a temporary directory and refuses a build that
is missing something the product needs at runtime. It is checked from here for
the same reason ``test_build_class1_splits.py`` checks the repo-root shim from
here: it is an executable the release depends on, and nothing else was reading
it.

**Why the split generator belongs on that list.** ``$MOLHUB_HOME/derived/
molcrafts/class1-universal-splits/1/`` is what every THEMol split view and every
prepared block is routed by, nobody publishes it, and the refusal a first-run
reader meets names exactly one way to produce it::

    python -m molhub.scripts.build_class1_splits

That command is a promise about the *installed* package. If
``molhub/scripts/build_class1_splits.py`` ever falls out of the wheel — a
``packages.find`` change, a missing ``__init__``, a rename — every THEMol
dataset becomes unopenable for a pip-installed user, and the refusal that was
supposed to rescue them names a module that is not there. The audit is the one
place that can catch it before a release, and it was checking ``cli.py``, the
manifest schema and one bundled registry file but not the derivation the
product's own error messages promise.

The list is read out of the script's source rather than by running it: the
script builds a wheel and shells out to ``uv`` and ``npm``, which is a release
gate, not a unit test. What is pinned is the *requirement it enforces*.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "check_package_contents.py"

#: The wheel path the split generator ships at, and therefore what
#: ``python -m molhub.scripts.build_class1_splits`` resolves to for an installed
#: reader. Spelled as a wheel member spells it — the archive's own separator,
#: not the platform's.
GENERATOR_WHEEL_PATH = "molhub/scripts/build_class1_splits.py"

#: The second executable molhub's own refusals promise: without it,
#: ``dataset:espaloma/phalkethoh-mm-small@1`` cannot be opened at all, and the
#: message that says so names ``python -m
#: molhub.scripts.convert_espaloma_phalkethoh_mm``. Same argument as the split
#: generator's, same consequence if it falls out of the wheel — the refusal
#: sends a pip-installed reader to a module that is not there.
CONVERTER_WHEEL_PATH = "molhub/scripts/convert_espaloma_phalkethoh_mm.py"

#: What the audit already required before the generator moved into the wheel.
#: Kept here so that adding a requirement cannot quietly replace one.
ALREADY_REQUIRED: frozenset[str] = frozenset(
    {
        "molhub/cli.py",
        "molhub/schema/manifest.schema.yaml",
        "molhub/catalog.py",
        "molhub/dataset/qm9.py",
        "molhub/dataset/themol_files.py",
    }
)


def required_wheel_files() -> frozenset[str]:
    """The wheel members ``check_package_contents.py`` refuses a build without.

    Read by parsing the script rather than importing or running it: importing it
    executes a ``uv build`` and two ``npm`` calls at module scope, which is a
    release gate rather than something a unit test may do.

    Returns:
        The declared set.

    Raises:
        AssertionError: If the script declares no ``required_wheel`` at all —
            a rename that would make every assertion below vacuous.
    """
    tree = ast.parse(AUDIT_SCRIPT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "required_wheel":
                return frozenset(ast.literal_eval(node.value))
    raise AssertionError(f"{AUDIT_SCRIPT} declares no required_wheel set")


class TestRequiredWheelContents:
    """The audit refuses a wheel that cannot run what the refusals promise."""

    def test_the_audit_script_is_where_it_is_expected(self):
        assert AUDIT_SCRIPT.is_file(), f"{AUDIT_SCRIPT} is missing"

    def test_it_declares_a_required_wheel_list(self):
        """Guards every assertion below from passing over a renamed variable."""
        assert required_wheel_files()

    def test_it_requires_the_split_generator(self):
        """The one derivation molhub's own error messages tell a reader to run."""
        assert GENERATOR_WHEEL_PATH in required_wheel_files()

    def test_it_requires_the_espaloma_converter(self):
        """The other command a refusal names, and the same failure if it is gone."""
        assert CONVERTER_WHEEL_PATH in required_wheel_files()

    def test_the_converter_is_in_the_source_tree_at_that_path(self):
        """A required member nothing builds is a gate that fails every release."""
        assert (REPO_ROOT / "src" / CONVERTER_WHEEL_PATH).is_file()

    @pytest.mark.parametrize("member", sorted(ALREADY_REQUIRED))
    def test_it_still_requires_what_it_already_required(self, member):
        assert member in required_wheel_files()

    def test_the_generator_is_in_the_source_tree_at_that_path(self):
        """A required member nothing builds is a gate that fails every release."""
        assert (REPO_ROOT / "src" / GENERATOR_WHEEL_PATH).is_file()

    def test_the_generator_package_declares_itself(self):
        """``packages.find`` collects packages, so the directory needs its
        ``__init__`` — which is also what makes ``-m`` resolve it."""
        assert (REPO_ROOT / "src" / "molhub" / "scripts" / "__init__.py").is_file()
