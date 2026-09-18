"""Structural constraints on the count-snapshot cache layer.

These are deliberately crude source-text checks. Their value is that they
are hard to satisfy accidentally and hard to work around quietly.

``molhub.cache`` sits below L3 (``dataset``) and above L0 (``config``): it
may import ``molhub.config`` and must not import ``molix``, ``molhub.dataset``,
``molhub.sources``, ``BlobStore``, ``DownloadCache``, ``molhub.loader``, or
``molhub.conveyor``. ``molhub.dataset`` may import ``molhub.cache``. The
layers below and beside it must not import it back.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

import molhub

_SRC = Path(molhub.__file__).parent
_REPO = _SRC.parent.parent
_CACHE_ROOT = _SRC / "cache"
_CACHE_FILES = (
    sorted(_CACHE_ROOT.rglob("*.py"))
    if _CACHE_ROOT.is_dir()
    else [_CACHE_ROOT / "__init__.py", _CACHE_ROOT / "counts.py"]
)
_SOURCES_FILES = sorted((_SRC / "sources").rglob("*.py"))
_LOADER_FILES = sorted((_SRC / "loader").rglob("*.py"))
_CONVEYOR_FILES = sorted((_SRC / "conveyor").rglob("*.py"))
_ISOLATOR_FILES = (
    _REPO / "tests" / "test_sources" / "conftest.py",
    _REPO / "tests" / "test_loader" / "conftest.py",
    _REPO / "tests" / "test_registry_data.py",
    _REPO / "tests" / "test_docs_examples.py",
    _REPO / "tests" / "test_dataset" / "test_csv_dataset.py",
    _REPO / "tests" / "test_dataset" / "test_threebpa.py",
    _REPO / "tests" / "test_dataset" / "test_revmd17.py",
    _REPO / "tests" / "test_cli.py",
    _REPO / "tests" / "test_scripts" / "test_build_class1_splits.py",
    _REPO / "tests" / "test_conveyor" / "test_tier.py",
    _REPO / "tests" / "test_dataset" / "test_cache.py",
)
_NEGATIVE_PROOF_CLASSES = frozenset({"TestConfig", "TestBlobStoreRoot"})
_SETENV_HOME = re.compile(r"setenv\(\s*[\"']MOLHUB_HOME[\"']")
_GET_HOME = re.compile(r"os\.environ\.get\(\s*[\"']MOLHUB_HOME[\"']")
_DEFAULTS_TO_HOME = re.compile(r"defaults to [`'\"]*\$MOLHUB_HOME", re.I)


def _imported_modules(path: Path) -> set[str]:
    """Every module name imported by *path*, flattened."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


def _cache_imports(name: str) -> bool:
    return name == "molhub.cache" or name.startswith("molhub.cache.")


def _without_hash_comments(text: str) -> str:
    """Drop ``#`` comments so leftover env uses cannot hide in gone-notes."""
    pieces: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type != tokenize.COMMENT:
                pieces.append(tok.string)
    except tokenize.TokenError:
        return text
    return "".join(pieces)


def _enclosing_class(text: str, lineno: int) -> str | None:
    current: str | None = None
    for i, line in enumerate(text.splitlines(), 1):
        match = re.match(r"^class (\w+)", line)
        if match:
            current = match.group(1)
        if i == lineno:
            return current
    return current


class TestCacheLayering:
    def test_the_package_directory_exists(self):
        assert _CACHE_ROOT.is_dir(), f"{_CACHE_ROOT} is missing"

    def test_the_package_declares_itself(self):
        assert (_CACHE_ROOT / "__init__.py").is_file()

    def test_the_cache_module_exists(self):
        assert (_CACHE_ROOT / "counts.py").is_file()

    @pytest.mark.parametrize("module_file", _CACHE_FILES, ids=lambda p: p.name)
    def test_cache_does_not_import_molix(self, module_file: Path):
        assert module_file.is_file(), f"{module_file} is missing"
        offenders = {
            name
            for name in _imported_modules(module_file)
            if name == "molix" or name.startswith("molix.")
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _CACHE_FILES, ids=lambda p: p.name)
    def test_cache_does_not_import_dataset(self, module_file: Path):
        assert module_file.is_file(), f"{module_file} is missing"
        offenders = {
            name
            for name in _imported_modules(module_file)
            if name == "molhub.dataset" or name.startswith("molhub.dataset.")
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _CACHE_FILES, ids=lambda p: p.name)
    def test_cache_does_not_import_sources(self, module_file: Path):
        assert module_file.is_file(), f"{module_file} is missing"
        offenders = {
            name
            for name in _imported_modules(module_file)
            if name == "molhub.sources" or name.startswith("molhub.sources.")
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _CACHE_FILES, ids=lambda p: p.name)
    def test_cache_does_not_import_blob_store(self, module_file: Path):
        assert module_file.is_file(), f"{module_file} is missing"
        offenders = {name for name in _imported_modules(module_file) if name == "BlobStore"}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _CACHE_FILES, ids=lambda p: p.name)
    def test_cache_does_not_import_download_cache(self, module_file: Path):
        assert module_file.is_file(), f"{module_file} is missing"
        offenders = {name for name in _imported_modules(module_file) if name == "DownloadCache"}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _CACHE_FILES, ids=lambda p: p.name)
    def test_cache_does_not_import_loader(self, module_file: Path):
        assert module_file.is_file(), f"{module_file} is missing"
        offenders = {
            name
            for name in _imported_modules(module_file)
            if name == "molhub.loader" or name.startswith("molhub.loader.")
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _CACHE_FILES, ids=lambda p: p.name)
    def test_cache_does_not_import_conveyor(self, module_file: Path):
        assert module_file.is_file(), f"{module_file} is missing"
        offenders = {
            name
            for name in _imported_modules(module_file)
            if name == "molhub.conveyor" or name.startswith("molhub.conveyor.")
        }
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _SOURCES_FILES, ids=lambda p: p.name)
    def test_sources_do_not_import_cache(self, module_file: Path):
        offenders = {name for name in _imported_modules(module_file) if _cache_imports(name)}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _LOADER_FILES, ids=lambda p: p.name)
    def test_loader_does_not_import_cache(self, module_file: Path):
        offenders = {name for name in _imported_modules(module_file) if _cache_imports(name)}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    @pytest.mark.parametrize("module_file", _CONVEYOR_FILES, ids=lambda p: p.name)
    def test_conveyor_does_not_import_cache(self, module_file: Path):
        offenders = {name for name in _imported_modules(module_file) if _cache_imports(name)}
        assert offenders == set(), f"{module_file.name} imports {sorted(offenders)}"

    #: The one module allowed to read ``$MOLHUB_HOME`` (operator ruling,
    #: 2026-09-18). The ban stays everywhere else, and for the reason it was
    #: written: a cache root resolved in several places is a root that can
    #: disagree with itself, which is why ``MOLHUB_CACHE_DIR`` was removed and
    #: this guard added. ``config.py`` reads the variable **once, at import**, to
    #: initialise ``config.home_dir`` — the single field every other module
    #: already goes through, so the number of places that decide the root is
    #: still one.
    #:
    #: Why the ruling reversed it: the variable was referenced in two modules
    #: and set by job scripts while nothing read it, so a launcher helper whose
    #: stated purpose was "keep the 4m extract off the 30 GiB home quota" did
    #: nothing, and 19 GiB re-downloaded onto a full /home
    #: (``Errno 122 Disk quota exceeded``, 2026-09-18).
    ENV_READER_ALLOWED = ("src/molhub/config.py",)

    def test_only_config_reads_molhub_home_env(self):
        offenders: list[str] = []
        alias = re.compile(r"(ENV_VAR|_HOME_ENV_VAR)\s*=\s*[\"']MOLHUB_HOME[\"']")
        for path in sorted(_SRC.rglob("*.py")):
            stripped = _without_hash_comments(path.read_text(encoding="utf-8"))
            if _GET_HOME.search(stripped) or alias.search(stripped):
                rel = str(path.relative_to(_REPO))
                if rel not in self.ENV_READER_ALLOWED:
                    offenders.append(rel)
        assert offenders == [], offenders

    def test_the_sanctioned_reader_actually_reads_it(self):
        """The allow-list must not outlive what it allows.

        If ``config.py`` stops reading the variable, this list is stale and the
        next module to read it would be allowed in by an entry nobody checked.
        """
        for rel in self.ENV_READER_ALLOWED:
            stripped = _without_hash_comments((_REPO / rel).read_text(encoding="utf-8"))
            assert "MOLHUB_HOME" in stripped, f"{rel} no longer reads MOLHUB_HOME"

    def test_molhub_cache_dir_survives_only_in_gone_comments(self):
        offenders: list[str] = []
        for path in sorted(_SRC.rglob("*.py")):
            stripped = _without_hash_comments(path.read_text(encoding="utf-8"))
            if "MOLHUB_CACHE_DIR" not in stripped:
                continue
            if re.search(r"MOLHUB_CACHE_DIR.*gone|gone.*MOLHUB_CACHE_DIR", stripped, re.I):
                continue
            offenders.append(str(path.relative_to(_REPO)))
        assert offenders == [], offenders

    def test_resolver_docs_do_not_default_to_molhub_home_env(self):
        resolver_docs = (
            _SRC / "molhub.py",
            _SRC / "cli.py",
            _SRC / "cache" / "counts.py",
            _SRC / "cache" / "__init__.py",
            _SRC / "dataset" / "cache.py",
            _SRC / "dataset" / "csv_dataset.py",
            _SRC / "loader" / "builder.py",
            _SRC / "loader" / "errors.py",
            _SRC / "sources" / "blobs.py",
            _SRC / "sources" / "fetcher.py",
            _SRC / "conveyor" / "__init__.py",
            _SRC / "conveyor" / "tier.py",
            _SRC / "conveyor" / "splits.py",
            _SRC / "scripts" / "__init__.py",
            _SRC / "scripts" / "build_class1_splits.py",
        )
        offenders: list[str] = []
        for path in resolver_docs:
            if not path.is_file():
                continue
            stripped = _without_hash_comments(path.read_text(encoding="utf-8"))
            if _DEFAULTS_TO_HOME.search(stripped) or "$MOLHUB_HOME" in stripped:
                if re.search(r"MOLHUB_HOME.*gone|gone.*MOLHUB_HOME", stripped, re.I):
                    continue
                offenders.append(str(path.relative_to(_REPO)))
        assert offenders == [], offenders

    def test_isolators_do_not_setenv_molhub_home(self):
        offenders: list[str] = []
        for path in _ISOLATOR_FILES:
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if _SETENV_HOME.search(line):
                    offenders.append(f"{path.relative_to(_REPO)}:{i}")
        assert offenders == [], offenders

    def test_setenv_molhub_home_is_only_a_negative_proof(self):
        offenders: list[str] = []
        for path in sorted((_REPO / "tests").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if not _SETENV_HOME.search(line):
                    continue
                owner = _enclosing_class(text, i)
                if owner not in _NEGATIVE_PROOF_CLASSES:
                    offenders.append(f"{path.relative_to(_REPO)}:{i}:{owner}")
        assert offenders == [], offenders

    def test_other_env_reads_remain(self):
        blob = "\n".join(path.read_text(encoding="utf-8") for path in _SRC.rglob("*.py"))
        assert "MOLHUB_REGISTRY" in blob
        assert "FIGSHARE_TOKEN" in blob
        assert "MOLHUB_SOURCE_BASE" in blob
        assert "MOLNEX_SRC" in blob
