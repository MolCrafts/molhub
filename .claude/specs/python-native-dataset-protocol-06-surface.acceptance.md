---
spec: python-native-dataset-protocol-06-surface
created: 2026-08-12
criteria:
  - id: ac-001
    summary: Barrel exports required dataset names
    type: code
    pass_when: |
      src/molhub/dataset/__init__.py __all__ contains QM9, RevMD17,
      ThreeBPA, ZincTyping, PhalkethohMM, CSV, dataset, DatasetManifest,
      resolve, and the six *Dataset aliases
    status: pending
  - id: ac-002
    summary: Short names are the *Dataset objects
    type: code
    pass_when: |
      tests/test_dataset/test_resolve.py::TestPublicSurface asserts
      QM9 is QM9Dataset, RevMD17 is RevMD17Dataset, ThreeBPA is
      ThreeBPADataset, ZincTyping is ZincTypingDataset, PhalkethohMM is
      PhalkethohMMDataset, and CSV is CSVDataset
    status: pending
  - id: ac-003
    summary: Root package does not import dataset
    type: code
    pass_when: |
      src/molhub/__init__.py has no import molhub.dataset / from molhub.dataset
      / from .dataset statement; molhub.__all__ excludes QM9, dataset, and
      resolve. The existing :mod:`molhub.dataset` docstring may remain.
    status: pending
  - id: ac-004
    summary: resolve full and kind-default both return QM9
    type: runtime
    pass_when: |
      tests/test_dataset/test_resolve.py::TestResolve asserts
      resolve("dataset:molcrafts/qm9@v2") is QM9 and
      resolve("molcrafts/qm9@v2") is QM9
    status: pending
  - id: ac-005
    summary: Importing QM9 does not call ArtifactHub
    type: runtime
    pass_when: |
      tests/test_dataset/test_resolve.py::TestImportCheapness shows
      from molhub.dataset import QM9 leaves Molhub.fetch (and any
      ArtifactHub.fetch) call count at 0
    status: pending
  - id: ac-006
    summary: README uses QM9().load() as primary dataset API
    type: docs
    pass_when: |
      README.md documents from molhub.dataset import QM9 and QM9().load()
      as the primary dataset usage, and does not show QM9Dataset(...) /
      len(source) / source[i] as the definition class itself being a
      MapDataset; MapDataset appears only as the collection protocol on
      the load() return
    status: pending
  - id: ac-007
    summary: CLAUDE.md dataset protocol sentence is the new contract
    type: docs
    pass_when: |
      CLAUDE.md 「molhub.dataset 的公开协议」 states decorator definitions
      plus load() materialization, and that MapDataset is the collection
      protocol on the return value
    status: pending
  - id: ac-008
    summary: product-02 dataset paragraph matches new API
    type: docs
    pass_when: |
      .claude/specs/molhub-product-02-clients-transport.md keeps
      status: implemented; Transport contract, Cache contract, and
      Conformance sections are unchanged; only ## Python dataset layer
      describes @dataset, DatasetManifest, resolve, short names, load(),
      and MapDataset as the collection protocol on the return, and retains
      Targets(frame), coordinate-not-URL, # source_id qualifier, and
      CSV-is-not-registry
    status: pending
  - id: ac-009
    summary: python.md lists public dataset symbols
    type: docs
    pass_when: |
      docs/reference/python.md has mkdocstrings entries for
      molhub.dataset.QM9, RevMD17, ThreeBPA, ZincTyping, PhalkethohMM,
      CSV, dataset, DatasetManifest, resolve, and MapDataset
    status: pending
  - id: ac-010
    summary: Regression locks import identity with no network
    type: runtime
    pass_when: |
      regressions/python-native-dataset-protocol-06-surface.py exits 0
      without opening a network socket; hard-coded asserts QM9 is
      QM9Dataset, resolve("dataset:molcrafts/qm9@v2") is QM9, and
      resolve("molcrafts/qm9@v2") is QM9; the script never calls load()
    status: pending
out_of_scope:
  - YAML schema changes
  - FrameCollection
  - L1 transport / cache / conformance
  - re-exporting dataset on the molhub root package
---

# Acceptance — python-native-dataset-protocol-06-surface

公开进口、包级 `resolve`、廉价 import、以及 README / CLAUDE / product-02 定点文档与代码合同一致。
