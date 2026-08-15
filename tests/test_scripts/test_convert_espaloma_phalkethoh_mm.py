"""Tests for the espaloma PhAlkEthOH converter, once it ships inside the wheel.

Mirrors ``src/molhub/scripts/convert_espaloma_phalkethoh_mm.py``
(``src/molhub/<area>/<module>.py`` → ``tests/test_<area>/test_<module>.py``, the
same mapping ``test_build_class1_splits.py`` follows).

**Why it moves out of ``scripts/``.** ``dataset:espaloma/phalkethoh-mm-small@1``
publishes a zip of DGL heterographs, and ``PhalkethohMMDataset`` reads a
converted tree — ``splits.json`` beside ``mols/`` — that only this conversion
produces. So the loader refuses the dataset and hands the reader a command; a
command that only exists in a git checkout is not one a pip-installed reader can
run, and the refusal that was supposed to rescue them names a file they do not
have. The split generator already made this move
(``molhub.scripts.build_class1_splits``); this is the second half of the same
promise, and the repository file becomes a shim rather than a second
implementation.

**Why ``--help`` must work without dgl.** dgl is not a molhub dependency and is
not installable in most of the environments molhub runs in — that is the whole
reason the conversion is offline and once. A reader who types the command the
refusal named will, more often than not, be in an environment without it, and
the first thing they type after that is ``--help``. Parsing arguments before
importing dgl costs nothing and is the difference between "here is what this
takes" and ``ModuleNotFoundError: No module named 'dgl'``.

**Nothing here imports dgl, and the whole file asserts that it cannot be.** The
refusal is only observable in an environment that genuinely lacks it, so
:func:`test_dgl_is_absent_from_this_environment` states that precondition as a
test rather than as a comment: if dgl ever lands in the dev extra, this file
goes red at the assumption rather than passing for the wrong reason.
"""

from __future__ import annotations

import importlib
import importlib.util
import runpy
import sys
import zipfile
from pathlib import Path

import pytest

#: The module under test, imported inside each test rather than at module scope:
#: it does not exist yet, and a module-level import would turn this whole file
#: into one collection error instead of failures with names on them (the rule
#: ``tests/test_loader/conftest.py`` states for its package).
MODULE = "molhub.scripts.convert_espaloma_phalkethoh_mm"

#: The command the loader's refusal names, and therefore what a reader types.
COMMAND = f"python -m {MODULE}"

#: The repository-root file that becomes a shim. It is not shipped in the wheel,
#: which is exactly why the implementation may not stay in it.
REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SCRIPT = REPO_ROOT / "scripts" / "convert_espaloma_phalkethoh_mm.py"

#: Fragments of the conversion itself. A shim that still carried any of them
#: would be a second implementation, and two producers of one tree drift with
#: nothing able to detect it — the reader has one directory either way.
CONVERSION_INTERNALS: tuple[str, ...] = (
    "import dgl",
    "load_graphs",
    "heterograph.bin",
    "HARTREE_TO_KCAL",
)

#: What the refusal has to name: the package, and how to get it. "install dgl"
#: with no version is an instruction that fails on the current release — the
#: conversion needs the 1.x line the espaloma notebook was written against.
DGL_REQUIREMENT = "dgl"


def test_dgl_is_absent_from_this_environment() -> None:
    """The precondition every refusal test below rests on.

    Stated as a test, not a comment: with dgl installed, "it refuses without
    dgl" is unobservable, and a suite that silently stopped checking it would
    keep passing while the refusal rotted.
    """
    assert importlib.util.find_spec("dgl") is None, (
        "dgl is importable here, so the refusals this file pins cannot be "
        "observed; molhub does not depend on it and the dev extra must not."
    )


@pytest.fixture
def converter():
    """The converter module, imported when a test asks for it."""
    return importlib.import_module(MODULE)


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    """A real zip file at a real path, holding none of what the converter wants.

    The refusal under test is *dgl is not here*, and it has to be the one that
    fires — so the source argument is a file that exists and opens. A missing
    path would let "no such file" pass for the answer.
    """
    path = tmp_path / "small_phalkethoh_mm.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("phalkethoh/README", "not a heterograph")
    return path


class TestConverterPackaging:
    """The converter is part of the product, not part of the checkout."""

    def test_it_ships_inside_the_package(self):
        """A pip install with no clone must still be able to run the conversion."""
        assert importlib.util.find_spec(MODULE) is not None

    def test_it_runs_as_a_module(self, monkeypatch: pytest.MonkeyPatch):
        """``python -m molhub.scripts.convert_espaloma_phalkethoh_mm`` is what the
        loader's refusal tells the reader to type, so the ``__main__`` entry has
        to be there."""
        monkeypatch.setattr(sys, "argv", ["convert_espaloma_phalkethoh_mm", "--help"])
        with pytest.raises(SystemExit) as raised:
            runpy.run_module(MODULE, run_name="__main__")
        assert raised.value.code == 0

    def test_its_usage_names_the_module_spelling(self, converter, capsys):
        """The usage line is where a reader copies the command from, and
        ``convert_espaloma_phalkethoh_mm.py`` — argparse's default from
        ``sys.argv[0]`` — is not a command a wheel user can run."""
        with pytest.raises(SystemExit):
            converter.main(["--help"])
        assert COMMAND in capsys.readouterr().out

    def test_the_repository_script_stays_as_a_shim(self):
        """The old path keeps working — it is in every runbook — by delegating."""
        assert MODULE in LEGACY_SCRIPT.read_text(encoding="utf-8")

    @pytest.mark.parametrize("fragment", CONVERSION_INTERNALS)
    def test_the_repository_script_holds_no_second_implementation(self, fragment: str):
        """Two producers of one converted tree drift, and nothing detects it: the
        dataset reads whichever one wrote the directory it was pointed at."""
        assert fragment not in LEGACY_SCRIPT.read_text(encoding="utf-8")


class TestHelpWithoutDgl:
    """Arguments are parsed before dgl is imported, so ``--help`` always answers."""

    def test_help_exits_zero(self, converter):
        """The reader is in an environment without dgl — that is why they are
        reading a converter's help at all."""
        with pytest.raises(SystemExit) as raised:
            converter.main(["--help"])
        assert raised.value.code == 0

    def test_help_names_the_source_argument(self, converter, capsys):
        with pytest.raises(SystemExit):
            converter.main(["--help"])
        assert "--src" in capsys.readouterr().out

    def test_help_names_the_output_argument(self, converter, capsys):
        with pytest.raises(SystemExit):
            converter.main(["--help"])
        assert "--out" in capsys.readouterr().out

    def test_help_says_the_conversion_needs_dgl(self, converter, capsys):
        """``--help`` is read *before* the command is run; finding out about the
        one dependency afterwards is finding out too late."""
        with pytest.raises(SystemExit):
            converter.main(["--help"])
        assert DGL_REQUIREMENT in capsys.readouterr().out.lower()


class TestConvertingWithoutDgl:
    """The refusal a reader without dgl meets, and what it leaves behind."""

    def test_it_exits_nonzero(self, converter, payload: Path, tmp_path: Path):
        """A conversion that cannot run is a failure, and a shell has to see it."""
        assert converter.main(["--src", str(payload), "--out", str(tmp_path / "out")]) != 0

    def test_it_returns_a_code_instead_of_raising(self, converter, payload: Path, tmp_path: Path):
        """``ModuleNotFoundError: No module named 'dgl'`` three frames into a
        conversion is the failure this refusal replaces: it names the module and
        nothing about why molhub wanted it or what to do next. Returning a code
        rather than raising is what the shipped generator already does, and one
        shape for one job is what makes ``python -m`` predictable."""
        code = converter.main(["--src", str(payload), "--out", str(tmp_path / "out")])
        assert isinstance(code, int)

    def test_the_refusal_names_the_package_it_needs(self, converter, payload, tmp_path, capsys):
        converter.main(["--src", str(payload), "--out", str(tmp_path / "out")])
        captured = capsys.readouterr()
        assert DGL_REQUIREMENT in (captured.out + captured.err).lower()

    def test_the_refusal_says_how_to_get_it(self, converter, payload, tmp_path, capsys):
        """A named dependency with no install line is a wall for anyone who has
        not met dgl's version pinning before."""
        converter.main(["--src", str(payload), "--out", str(tmp_path / "out")])
        captured = capsys.readouterr()
        assert "pip install" in (captured.out + captured.err).lower()

    def test_the_refusal_writes_nothing(self, converter, payload: Path, tmp_path: Path):
        """Fail closed: half a converted tree is one ``PhalkethohMMDataset`` will
        happily open and quietly under-report."""
        out = tmp_path / "out"
        converter.main(["--src", str(payload), "--out", str(out)])
        assert not out.exists()

    def test_the_refusal_reaches_stderr(self, converter, payload, tmp_path, capsys):
        """So a run that pipes its stdout somewhere still shows the reason."""
        converter.main(["--src", str(payload), "--out", str(tmp_path / "out")])
        assert DGL_REQUIREMENT in capsys.readouterr().err.lower()


class TestPublishedConstants:
    """The two numbers that make this "the espaloma conversion" and not another.

    They move with the implementation, so they are checked where the
    implementation now lives: a shipped module that quietly reseeded the split
    or rounded the Hartree constant would produce a tree the dataset opens
    happily and that is not the published experiment.
    """

    def test_the_split_seed_is_the_published_one(self, converter):
        """2666, from the espaloma notebook: the split is only *the espaloma
        split* because the seed is theirs."""
        assert converter.DEFAULT_SEED == 2666

    def test_the_energy_conversion_is_the_published_constant(self, converter):
        """1 Hartree = 627.5094740631 kcal/mol, hard-coded so a "cleanup" to a
        rounder one shows up as a failing test rather than a shifted scale."""
        assert converter.HARTREE_TO_KCAL == 627.5094740631
