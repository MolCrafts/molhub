"""Build and audit Python/npm publication contents in disposable directories."""

from __future__ import annotations

import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORBIDDEN = ("tests/", ".dev.vars", "__pycache__", ".pytest_cache", ".rsbuild", ".wrangler")


def assert_clean(files: list[str], label: str) -> None:
    offenders = [name for name in files if any(part in name for part in FORBIDDEN)]
    if offenders:
        raise SystemExit(f"{label} contains forbidden files: {offenders}")


with tempfile.TemporaryDirectory(prefix="molhub-package-audit-") as temporary:
    output = Path(temporary)
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(output)], cwd=ROOT, check=True)
    wheel = next(output.glob("molhub-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        wheel_files = archive.namelist()
    assert_clean(wheel_files, "Python wheel")
    required_wheel = {
        "molhub/cli.py",
        "molhub/schema/manifest.schema.yaml",
        "molhub/registry_data/dataset/molcrafts/qm9/v2.yaml",
    }
    missing_wheel = required_wheel.difference(wheel_files)
    if missing_wheel:
        raise SystemExit(f"Python wheel is missing runtime files: {sorted(missing_wheel)}")

    subprocess.run(
        ["npm", "run", "build", "--workspace", "@molcrafts/molhub"], cwd=ROOT, check=True
    )
    packed = subprocess.run(
        ["npm", "pack", "--dry-run", "--json", "--workspace", "@molcrafts/molhub"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    package = json.loads(packed.stdout)[0]
    npm_files = [item["path"] for item in package["files"]]
    assert_clean(npm_files, "npm tarball")
    required_npm = {"dist/cli.js", "dist/generated-manifest-schema.js", "dist/node.js"}
    missing_npm = required_npm.difference(npm_files)
    if missing_npm:
        raise SystemExit(f"npm tarball is missing runtime files: {sorted(missing_npm)}")

    print(f"package audit: {len(wheel_files)} wheel files, {len(npm_files)} npm files")
