"""Public-API regression for python-native-dataset-protocol-01-types.

tool: python
command: uv run python regressions/python-native-dataset-protocol-01-types.py
date: 2026-08-12
"""

from __future__ import annotations

import json
from dataclasses import asdict

from molhub.dataset import DatasetManifest, Datasets, dataset


@dataset(name="dummy", namespace="molcrafts", version="1.0")
class Dummy:
    pass


assert Dummy.manifest.canonical == "dataset:molcrafts/dummy@1.0"
assert isinstance(Dummy.manifest, DatasetManifest)
assert asdict(Dummy.manifest)["coordinate"] == {
    "kind": "dataset",
    "namespace": "molcrafts",
    "name": "dummy",
    "version": "1.0",
}
json.dumps(asdict(Dummy.manifest))
assert Datasets.of(Dummy).resolve("dataset:molcrafts/dummy@1.0") is Dummy
Dummy()
print("python-native-dataset-protocol-01-types: OK")
