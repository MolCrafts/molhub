---
spec: python-native-dataset-protocol-01-types
created: 2026-08-12
criteria:
  - id: ac-001
    summary: DatasetManifest is frozen and JSON-serializable via asdict
    type: code
    pass_when: |
      DatasetManifest in src/molhub/dataset/definition.py is a
      dataclasses.dataclass(frozen=True) (not pydantic). dataclasses.asdict
      yields coordinate as {kind, namespace, name, version} strings plus
      description, license, homepage, citation, tags; json.dumps(asdict(m))
      succeeds with no custom encoder. Mutation of a field raises.
    status: pending
  - id: ac-002
    summary: Decorator attaches DatasetManifest with Coordinate identity
    type: code
    pass_when: |
      @dataset(name, namespace, version, optional description/license/homepage/citation/tags)
      is exported as dataset, sets Cls.manifest to a DatasetManifest whose
      coordinate equals Coordinate(kind="dataset", namespace=..., name=...,
      version=...) and whose canonical is dataset:<namespace>/<name>@<version>.
      Invalid name/namespace/version raise InvalidCoordinate from Coordinate
      (same character rules as tests/test_coordinate.py); kind is not a
      decorator argument.
    status: pending
  - id: ac-003
    summary: Decorated class construction performs no IO
    type: code
    pass_when: |
      Decorating an empty class does not wrap __init__ and does not import or
      call ArtifactHub, Molhub, fetch, open, or load. Cls() succeeds with no
      filesystem or network access. TestDataset covers this on a dummy class.
    status: pending
  - id: ac-004
    summary: Datasets is immutable and later-write-wins on resolve
    type: code
    pass_when: |
      Datasets.of / with_dataset return a new collection; the receiver is
      unchanged. A later with_dataset for the same canonical wins.
      resolve(str|Coordinate) uses Coordinate.coerce, rejects kind!="dataset"
      with InvalidCoordinate, returns the class on hit, and raises
      UnknownDataset (KeyError) listing known canonicals on miss.
    status: pending
  - id: ac-005
    summary: molhub.dataset exports declaration-surface symbols
    type: code
    pass_when: |
      src/molhub/dataset/__init__.py imports and lists in __all__ the names
      dataset, DatasetManifest, Datasets, and UnknownDataset. There is no
      package-level resolve function in this spec.
    status: pending
  - id: ac-006
    summary: Public symbols have Google-style docstrings
    type: docs
    pass_when: |
      dataset, DatasetManifest, Datasets, and UnknownDataset in
      src/molhub/dataset/definition.py have Google-style docstrings (Args /
      Returns / Raises as applicable) stating kind is dataset and that the
      manifest is IO-free.
    status: pending
  - id: ac-007
    summary: Regression reproduces dummy identity and resolve goldens
    type: runtime
    evaluator_hint: "script: regressions/python-native-dataset-protocol-01-types.py"
    pass_when: |
      uv run python regressions/python-native-dataset-protocol-01-types.py
      exits 0 after decorating a dummy class and asserting the hard-coded
      literals Dummy.manifest.canonical == "dataset:molcrafts/dummy@1.0",
      asdict(Dummy.manifest)["coordinate"] == {"kind": "dataset",
      "namespace": "molcrafts", "name": "dummy", "version": "1.0"},
      json.dumps(asdict(Dummy.manifest)) succeeds, Datasets.of(Dummy).resolve(
      "dataset:molcrafts/dummy@1.0") is Dummy, and Dummy() succeeds. No
      third-party oracle is imported or subprocessed.
    status: pending
  - id: ac-008
    summary: definition.py stays IO-free with no global registry dict
    type: code
    pass_when: |
      src/molhub/dataset/definition.py source text contains no pydantic,
      ArtifactHub, Molhub, molhub.sources, or molhub.registry imports, and
      does not bind a module-level mutable dict as a dataset registry.
      Datasets holds its mapping on the instance only.
    status: pending
  - id: ac-009
    summary: Built-in dataset implementation modules stay unchanged
    type: code
    pass_when: |
      This spec's diff does not modify src/molhub/dataset/qm9.py,
      revmd17.py, threebpa.py, csv_dataset.py, zinc_typing.py,
      phalkethoh_mm.py, protocol.py, hub.py, or spec/manifest.schema.yaml.
    status: pending
out_of_scope:
  - fetch/open/load and any IO from Cls()
  - migrating built-in *Dataset classes (04/05)
  - package-level molhub.dataset.resolve (06)
  - generalizing MapDataset/IterableDataset/InMemoryDataset (03)
  - pydantic and custom JSON encoders
  - YAML registry / spec/manifest.schema.yaml / L2 Manifest
  - molpy FrameCollection hierarchy
  - treating molpy.Trajectory as a generic dataset
  - HTTP range, entry-point discovery, Datasets.builtin/discover
---

# Acceptance — python-native-dataset-protocol-01-types

声明面完成：冻结可序列化的 `DatasetManifest`、`@dataset` 附着身份、不可变 `Datasets` 编目，以及不触发 IO 的构造。不含取数、不含内置数据集迁移。

## AC-001 — DatasetManifest is frozen and JSON-serializable via asdict

`DatasetManifest` 必须是 frozen dataclass，stdlib `asdict` 即可 JSON 序列化。

## AC-002 — Decorator attaches DatasetManifest with Coordinate identity

`@dataset` 小写；身份是 `Coordinate(kind="dataset", ...)`；非法分段抛 `InvalidCoordinate`。

## AC-003 — Decorated class construction performs no IO

装饰只附着清单，不包装构造，不 fetch。

## AC-004 — Datasets is immutable and later-write-wins on resolve

编目仿 `Drivers` 不可变与后写覆盖；未命中抛 `UnknownDataset`。

## AC-005 — molhub.dataset exports declaration-surface symbols

导出四个符号；本阶段没有包级 `resolve`。

## AC-006 — Public symbols have Google-style docstrings

新公开符号有 Google 风格 docstring。

## AC-007 — Regression reproduces dummy identity and resolve goldens

回归脚本硬编码 `dataset:molcrafts/dummy@1.0` 等字面量。

## AC-008 — definition.py stays IO-free with no global registry dict

`definition.py` 不引入传输/registry/pydantic，无模块级可变注册表。

## AC-009 — Built-in dataset implementation modules stay unchanged

本规格不改内置数据集实现与 YAML schema。
