"""Fixtures shared across the coordinate / manifest / registry / hub tests."""

from __future__ import annotations

import hashlib

import pytest


def pytest_configure() -> None:
    """Let tests compare molpy ``MetaValue`` wrappers to Python scalars.

    ``frame.meta[key]`` is a ``MetaValue``; the documented numbers live on
    ``.value``. Production code unwraps at the few sites that need a scalar.
    Tests keep asserting the numbers they already pin.
    """
    import molrs

    def _unwrap(value):  # noqa: ANN001
        return getattr(value, "value", value)

    def _eq(self, other):  # noqa: ANN001
        return _unwrap(self) == _unwrap(other)

    def _lt(self, other):  # noqa: ANN001
        return _unwrap(self) < _unwrap(other)

    molrs.core.MetaValue.__eq__ = _eq  # type: ignore[method-assign]
    molrs.core.MetaValue.__lt__ = _lt  # type: ignore[method-assign]
    molrs.core.MetaValue.__float__ = lambda self: float(self.value)  # type: ignore[method-assign]
    molrs.core.MetaValue.__int__ = lambda self: int(self.value)  # type: ignore[method-assign]
    molrs.core.MetaValue.__index__ = lambda self: int(self.value)  # type: ignore[method-assign]
    molrs.core.MetaValue.__str__ = lambda self: str(self.value)  # type: ignore[method-assign]
    molrs.core.MetaValue.__hash__ = lambda self: hash(self.value)  # type: ignore[method-assign]


MAIN_BODY = b"main artifact bytes"
MAIN_SHA = hashlib.sha256(MAIN_BODY).hexdigest()
MAIN_MD5 = hashlib.md5(MAIN_BODY).hexdigest()
SIDE_BODY = b"side artifact bytes"
SIDE_SHA = hashlib.sha256(SIDE_BODY).hexdigest()
SIDE_MD5 = hashlib.md5(SIDE_BODY).hexdigest()

_SIDE_ARTIFACT = f"""\
  - role: exclude
    filename: excluded.txt
    digest: "md5:{SIDE_MD5}"
    locators:
      - fake://side
"""


def manifest_yaml(
    *,
    name: str = "qm9",
    version: str = "v2",
    kind: str = "dataset",
    namespace: str = "molcrafts",
    schema_version: int = 1,
    with_side: bool = True,
) -> str:
    """A valid manifest, with a comment in it so comment handling stays covered."""
    return (
        "# Curated by hand; digests are copied from what the platform publishes.\n"
        f"schema_version: {schema_version}\n"
        f"kind: {kind}\n"
        f"namespace: {namespace}\n"
        f"name: {name}\n"
        f"version: {version}\n"
        "\n"
        "title: QM9 — 134k small organic molecules\n"
        "description: Quantum-chemical properties for small organic molecules.\n"
        "license: CC0-1.0\n"
        "doi: 10.1038/sdata.2014.22\n"
        "\n"
        "artifacts:\n"
        "  - role: main\n"
        "    filename: qm9.tar.bz2\n"
        "    format: tar-bz2\n"
        "    media_type: application/x-bzip2\n"
        f'    digest: "md5:{MAIN_MD5}"\n'
        "    size: 19\n"
        "    locators:\n"
        "      - fake://main          # preferred mirror\n"
        "      - fake://main-backup\n"
        f"{_SIDE_ARTIFACT if with_side else ''}"
        "\n"
        "targets:\n"
        "  graph_level: [U0, gap, homo]\n"
        "  atom_level: []\n"
    )


@pytest.fixture
def registry_dir(tmp_path):
    """A registry directory holding one dataset manifest."""
    root = tmp_path / "registry"
    path = root / "dataset" / "molcrafts" / "qm9" / "v2.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(manifest_yaml(), encoding="utf-8")
    return root


@pytest.fixture
def bodies():
    """The bytes the fake source should serve for the fixture manifest."""
    return {"main": MAIN_BODY, "main-backup": MAIN_BODY, "side": SIDE_BODY}


@pytest.fixture(autouse=True)
def _home_is_never_the_user_s(request, tmp_path_factory, monkeypatch):
    """Point ``config.home_dir`` at a throwaway directory for every test.

    ``config.home_dir`` defaults to ``~/.cache/molhub``, and everything that
    caches lands under it — a count sidecar, a download, an extracted
    tarball. A test that writes there leaves state behind for the next run
    and for the person whose machine it is; a test that *reads* there is
    asserting against whatever happens to be on this machine rather than
    against the code. Both are silent: the suite passes either way.

    Autouse, because the property being protected is not a property of any
    one test. A test whose subject *is* the default may opt out with
    ``@pytest.mark.real_home_default``; there should be very few.
    """
    from molhub.config import config

    if "real_home_default" in request.keywords:
        return config.home_dir

    root = tmp_path_factory.mktemp("molhub-home")
    monkeypatch.setattr(config, "home_dir", root, raising=False)
    return root
