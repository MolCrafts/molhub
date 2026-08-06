"""Fixtures shared across the coordinate / manifest / index / hub tests."""

from __future__ import annotations

import hashlib

import pytest

MAIN_BODY = b"main artifact bytes"
MAIN_SHA = hashlib.sha256(MAIN_BODY).hexdigest()
MAIN_MD5 = hashlib.md5(MAIN_BODY).hexdigest()
SIDE_BODY = b"side artifact bytes"
SIDE_SHA = hashlib.sha256(SIDE_BODY).hexdigest()

_SIDE_ARTIFACT = f"""\
  - role: exclude
    filename: excluded.txt
    sha256: "{SIDE_SHA}"
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
        "# Curated by hand; the bot fills in sha256 on first publish.\n"
        f"schema_version: {schema_version}\n"
        f"kind: {kind}\n"
        f"namespace: {namespace}\n"
        f"name: {name}\n"
        f"version: {version}\n"
        "\n"
        "title: QM9 — 134k small organic molecules\n"
        "description: Quantum-chemical properties for small organic molecules.\n"
        "license: CC0-1.0\n"
        "citation: 10.1038/sdata.2014.22\n"
        "\n"
        "artifacts:\n"
        "  - role: main\n"
        "    filename: qm9.tar.bz2\n"
        f'    sha256: "{MAIN_SHA}"\n'
        "    size: 19\n"
        f'    upstream_digest: "md5:{MAIN_MD5}"\n'
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
def index_dir(tmp_path):
    """An index directory holding one dataset manifest."""
    root = tmp_path / "index"
    path = root / "dataset" / "molcrafts" / "qm9" / "v2.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(manifest_yaml(), encoding="utf-8")
    return root


@pytest.fixture
def bodies():
    """The bytes the fake registry should serve for the fixture manifest."""
    return {"main": MAIN_BODY, "main-backup": MAIN_BODY, "side": SIDE_BODY}
