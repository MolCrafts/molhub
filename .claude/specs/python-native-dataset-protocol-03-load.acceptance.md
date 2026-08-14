---
spec: python-native-dataset-protocol-03-load
created: 2026-08-12
criteria:
  - id: ac-001
    summary: InMemoryDataset iterates, slices to same type, materializes
    type: code
    pass_when: |
      tests/test_dataset/test_protocol.py::TestInMemoryDataset covers
      __iter__ yielding Frames, __getitem__(int) returning a Frame,
      __getitem__(slice) returning InMemoryDataset (not list) with the
      sliced length, and materialize() returning an in-memory equivalent
      (self or InMemoryDataset of equal length and the same source_id).
    status: pending
  - id: ac-002
    summary: IterableDataset is a collection capability, not a definition
    type: code
    pass_when: |
      isinstance(InMemoryDataset([]), IterableDataset) is True; a
      stream-only object with source_id and __iter__ remains
      IterableDataset and not MapDataset; a three-tuple-only stub with
      source_id/__len__/__getitem__(int) and no __iter__ or materialize
      remains MapDataset and is not IterableDataset; a QM9 definition
      instance is neither IterableDataset nor MapDataset. InMemoryDataset
      must not be used as the map-only negative.
    status: pending
  - id: ac-003
    summary: SubsetDataset still wraps MapDataset collections
    type: code
    pass_when: |
      SubsetDataset(InMemoryDataset(frames), [0]) is still a MapDataset;
      slice returns SubsetDataset whose source_id equals the parent
      subset source_id; materialize() returns InMemoryDataset with that
      same source_id; unnamed source_id keeps :subset= and named views
      keep #split=.
    status: pending
  - id: ac-004
    summary: QM9 is a decorated definition, not a MapDataset
    type: code
    pass_when: |
      QM9 is decorated with @dataset(name="qm9", namespace="molcrafts",
      version="v2"); QM9.manifest.canonical == "dataset:molcrafts/qm9@v2";
      the module holds no upstream URL; isinstance(QM9(), MapDataset) is
      False; QM9Dataset is QM9.
    status: pending
  - id: ac-005
    summary: QM9() and import do not fetch
    type: code
    pass_when: |
      Constructing QM9(..., download=True, hub=hub) leaves hub.calls
      empty; import of molhub.dataset.qm9 does not call ArtifactHub.fetch;
      missing offline files raise FileNotFoundError from load(), not
      __init__; QM9 has no download classmethod.
    status: pending
  - id: ac-006
    summary: QM9.load() returns InMemoryDataset of Frames
    type: code
    pass_when: |
      With the miniature fixture tarball or FakeHub, QM9(...).load() is
      an InMemoryDataset (not molpy.Trajectory), samples are molpy.Frame
      with an atoms block, and Targets.read() sees graph-level keys
      written by Targets.write.
    status: pending
  - id: ac-007
    summary: load() collections support slice, iter, and materialize
    type: code
    pass_when: |
      tests/test_dataset/test_qm9.py asserts load()[:n] is InMemoryDataset
      of length n, list(iter(collection)) has the full length, and
      materialize() is InMemoryDataset of that same length.
    status: pending
  - id: ac-008
    summary: TARGET_SCHEMA and source_id view rules stay unchanged
    type: code
    pass_when: |
      QM9.TARGET_SCHEMA.graph_level == QM9.ALL_TARGETS and atom_level is
      empty; unknown targets raise ValueError at __init__; source_id is
      dataset:molcrafts/qm9@v2 or #total= / #targets= qualifiers; load()
      copies that source_id onto the returned InMemoryDataset.
    status: pending
  - id: ac-009
    summary: Fetch happens in load()/fetch(), not construction
    type: code
    pass_when: |
      download=True load() records hub.fetch of the pinned coordinate;
      download=False load() never touches the hub; view params total and
      targets remain on QM9.__init__; hub injection still works.
    status: pending
  - id: ac-010
    summary: test_qm9 and the network count assertion use load()
    type: code
    pass_when: |
      tests/test_dataset/test_qm9.py uses load() for len/getitem and stays
      green under uv run pytest tests/test_dataset/test_qm9.py -v;
      tests/test_registry_data.py sample-count assertion calls load()
      before len(); src/molhub/dataset/__init__.py exports QM9 and
      QM9Dataset.
    status: pending
  - id: ac-011
    summary: Public load/collection methods have Google docstrings
    type: docs
    pass_when: |
      QM9.load, InMemoryDataset.__getitem__, and
      InMemoryDataset.materialize have Google-style docstrings (Args /
      Returns / Raises as applicable) stating Frame coordinates are
      angstrom as published and graph targets are as published, with no
      unit conversion in this spec.
    status: pending
  - id: ac-012
    summary: Regression reproduces fixture atom count and target keys
    type: runtime
    evaluator_hint: "script: regressions/python-native-dataset-protocol-03-load.py"
    pass_when: |
      uv run python regressions/python-native-dataset-protocol-03-load.py
      exits 0 after constructing decorated QM9 against a FakeHub serving
      a tiny in-script fixture tarball (no network), calling load(), and
      asserting the hard-coded literals for collection length, per-frame
      atom count (1) or the 15 QM9 graph target keys, load()[:n] as
      InMemoryDataset, iteration length, and materialize() as
      InMemoryDataset. No third-party oracle is imported or subprocessed.
    status: pending
out_of_scope:
  - migrating other built-in datasets (04/05)
  - package-level resolve and README (06)
  - molpy FrameCollection
  - returning Trajectory from QM9.load()
  - stream/preview APIs on Molhub
  - MoleculeSplit changes
---

# Acceptance — python-native-dataset-protocol-03-load

`load()` 是唯一取数入口；返回 generalize 后的 `InMemoryDataset`；QM9 是定义类而不是集合；构造与 import 不 fetch。
