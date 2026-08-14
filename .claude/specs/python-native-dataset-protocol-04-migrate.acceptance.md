---
spec: python-native-dataset-protocol-04-migrate
created: 2026-08-12
criteria:
  - id: ac-001
    summary: Short names and *Dataset aliases are exported
    type: code
    pass_when: |
      src/molhub/dataset/revmd17.py defines RevMD17 and RevMD17Dataset is
      RevMD17; threebpa.py defines ThreeBPA and ThreeBPADataset is ThreeBPA;
      csv_dataset.py defines CSV and CSVDataset is CSV.
      src/molhub/dataset/__init__.py imports and lists in __all__ RevMD17,
      RevMD17Dataset, ThreeBPA, ThreeBPADataset, CSV, and CSVDataset.
    status: pending
  - id: ac-002
    summary: Definition classes are not MapDataset
    type: code
    pass_when: |
      RevMD17, ThreeBPA, and CSV instances are not MapDataset (no __len__ /
      __getitem__ on the handle). TestRevMD17, TestThreeBPA, and TestCSV
      assert isinstance(handle, MapDataset) is False and
      isinstance(handle.load(), InMemoryDataset).
    status: pending
  - id: ac-003
    summary: Coordinate handles use @dataset identity only
    type: code
    pass_when: |
      RevMD17.manifest.canonical == "dataset:molcrafts/revmd17@v4" and
      ThreeBPA.manifest.canonical == "dataset:molcrafts/3bpa@v1", matching
      each module COORDINATE. Neither revmd17.py nor threebpa.py defines
      BASE_URL or a figshare/github/http URL constant. CSV has no
      DatasetManifest / COORDINATE and is not decorated with @dataset.
    status: pending
  - id: ac-004
    summary: Import and construction perform no byte fetch
    type: runtime
    pass_when: |
      After RevMD17(..., hub=fake) or ThreeBPA(..., hub=fake), fake.calls is
      empty. After CSV(url, cache=injected), the fake FileTransfer has no
      fetches. Importing the three modules does not call ArtifactHub.fetch
      or DownloadCache.fetch.
    status: pending
  - id: ac-005
    summary: load() returns InMemoryDataset with preserved source_id
    type: runtime
    pass_when: |
      RevMD17(molecule="aspirin", hub=fake).load().source_id equals
      "dataset:molcrafts/revmd17@v4#molecule=aspirin";
      ThreeBPA(tag="train_300K", hub=fake).load().source_id equals
      "dataset:molcrafts/3bpa@v1#split=train_300K"; CSV(local).load()
      .source_id starts with "csv:" and contains no "@". The text before
      "#" on the two coordinate ids Coordinate.parse-roundtrips to
      COORDINATE. load() is not a molpy.Trajectory.
    status: pending
  - id: ac-006
    summary: Coordinate fetch asks hub for one role only
    type: runtime
    pass_when: |
      RevMD17(molecule="aspirin", hub=fake).fetch() records
      fake.calls == [(COORDINATE, ["aspirin"])] and returns the served
      NPZ path. ThreeBPA(tag="train_300K", hub=fake).fetch() records
      roles ["train_300K"] only. Unknown molecule or tag raises
      ValueError at construction with hub.calls still empty.
    status: pending
  - id: ac-007
    summary: CSV fetch uses DownloadCache, never ArtifactHub
    type: runtime
    pass_when: |
      CSV(local_path).fetch() returns that path without ArtifactHub.
      CSV(https URL, cache=DownloadCache(tmp, transfer=fake)).fetch()
      writes under tmp/urls/ and not tmp/files/. Missing local path
      raises FileNotFoundError on fetch/load, not on construction.
    status: pending
  - id: ac-008
    summary: TARGET_SCHEMA and Targets layout stay unchanged
    type: runtime
    pass_when: |
      RevMD17.TARGET_SCHEMA still has graph_level energy and atom_level
      forces; ThreeBPA.TARGET_SCHEMA likewise; fixture frames expose
      energy via Targets.read() and fx/fy/fz columns. CSV rows land in
      Targets; first sample labels.Exp_Tg(K) is 345.15.
    status: pending
  - id: ac-009
    summary: Regression reproduces fixture goldens offline
    type: runtime
    evaluator_hint: "script: regressions/python-native-dataset-protocol-04-migrate.py"
    pass_when: |
      uv run python regressions/python-native-dataset-protocol-04-migrate.py
      exits 0 after building the in-script fake hub plus tiny NPZ /
      extxyz / CSV fixtures and asserting hard-coded literals: revMD17
      len==3, load()[:1] len==1, source_id
      "dataset:molcrafts/revmd17@v4#molecule=aspirin", first energy
      -10.0; ThreeBPA len==2, source_id
      "dataset:molcrafts/3bpa@v1#split=train_300K", first energy -40.50;
      CSV len==5, source_id startswith "csv:", first Tg 345.15. No
      network and no third-party oracle import or subprocess.
    status: pending
  - id: ac-010
    summary: Public load/fetch docstrings state units and no-IO construct
    type: docs
    pass_when: |
      RevMD17, ThreeBPA, CSV, fetch, and load in the three modules have
      Google-style docstrings. RevMD17 documents Å, kcal/mol, and
      kcal/(mol·Å). All three state that construction does not fetch
      and that load() returns InMemoryDataset.
    status: pending
out_of_scope:
  - ZincTyping / PhalkethohMM
  - MoleculeSplit and package-level resolve
  - FrameCollection / Trajectory
  - YAML schema changes
---

# Acceptance — python-native-dataset-protocol-04-migrate

三个读取器迁到 QM9-after-03 交互；CSV 无假坐标；`load()` 返回 `InMemoryDataset`。
