---
spec: python-native-dataset-protocol-05-mm
created: 2026-08-12
criteria:
  - id: ac-001
    summary: Short names and *Dataset aliases are the same classes
    type: code
    pass_when: |
      molhub.dataset exports ZincTyping, PhalkethohMM, ZincTypingDataset, and
      PhalkethohMMDataset; ZincTypingDataset is ZincTyping; PhalkethohMMDataset
      is PhalkethohMM; all four names appear in molhub.dataset.__all__;
      ZincTyping.manifest.canonical == "dataset:espaloma/zinc-typing@1" ==
      COORDINATE; PhalkethohMM.manifest.canonical ==
      "dataset:espaloma/phalkethoh-mm-small@1" == COORDINATE.
    status: pending
  - id: ac-002
    summary: Definition instances are not MapDataset
    type: code
    pass_when: |
      ZincTyping(root, split="train") and PhalkethohMM(root) do not satisfy
      isinstance(..., MapDataset) and do not implement usable __len__/__getitem__;
      TestZincTyping and TestPhalkethohMM assert this on the fixture root.
    status: pending
  - id: ac-003
    summary: load() returns InMemoryDataset with #split= source_id
    type: code
    pass_when: |
      ZincTyping(root, split="train").load() is an InMemoryDataset/MapDataset,
      is not molpy.Trajectory, has len 3 and source_id
      dataset:espaloma/zinc-typing@1#split=train; ZincTyping(root, split=None)
      .load() has len 5 and source_id dataset:espaloma/zinc-typing@1;
      PhalkethohMM(root).load() has len 4 and source_id
      dataset:espaloma/phalkethoh-mm-small@1; PhalkethohMM(root, split="train")
      .load() has source_id dataset:espaloma/phalkethoh-mm-small@1#split=train.
    status: pending
  - id: ac-004
    summary: Import and construct do not fetch
    type: code
    pass_when: |
      Constructing ZincTyping or PhalkethohMM with a FakeHub and a missing root
      leaves hub.calls empty; the first fetch appears only inside load() as
      (COORDINATE, ["main"]) for that class's pinned coordinate.
    status: pending
  - id: ac-005
    summary: MolecularFrame and MoleculeSplit are removed
    type: code
    pass_when: |
      molhub.dataset does not export MolecularFrame, MoleculeSplit, or
      KNOWN_SPLIT_SCHEMES; src/molhub/dataset/molecular.py defines no
      those types; identity is read with Targets(frame)[MOLECULE_ID].
    status: pending
  - id: ac-006
    summary: Frame identity schema and coordinates stay pinned
    type: code
    pass_when: |
      After load(), zinc fixture frame 0 has molecule_id m00, atom_type [c3, hc],
      bonds (0,1); phalkethoh train frames have mm_energy -1.0 and -1.5,
      atoms.x[1] 1.0 and 1.1, and TARGET_SCHEMA/COORDINATE class attributes
      equal the pre-migration values; MOLECULE_ID, CONFORMER_ID, and
      MolecularUnits remain exported.
    status: pending
  - id: ac-007
    summary: Legacy mm-param-val regressions call load()
    type: code
    pass_when: |
      regressions/mm-param-val-02-zinc-typing.py and
      regressions/mm-param-val-03-phalkethoh-mm.py index only the object returned
      by .load() and still assert the same hard-coded goldens (zinc train/val/test
      lengths 3/1/1, atom_type [c3, hc]; phalkethoh full len 4 and train
      mm_energy -1.0/-1.5). Neither script passes download=; 02 does not read
      .molecule_ids or .split_table on the collection.
    status: pending
  - id: ac-008
    summary: Spec regression reproduces hard-coded MM protocol goldens
    type: runtime
    pass_when: |
      python regressions/python-native-dataset-protocol-05-mm.py exits 0 and
      prints python-native-dataset-protocol-05-mm: OK after reproducing the
      script's hard-coded literals: zinc train len 3 and source_id
      dataset:espaloma/zinc-typing@1#split=train, frame0 molecule_id m00 and
      atom_type [c3, hc]; phalkethoh train mm_energy -1.0 and -1.5; load()
      result is Dataset and not Trajectory; ZincTyping is ZincTypingDataset
      and PhalkethohMM is PhalkethohMMDataset; identity is Targets(frame)[MOLECULE_ID].
      No third-party process is started.
    status: pending
  - id: ac-009
    summary: Adapters hold only the two pinned coordinates
    type: code
    pass_when: |
      zinc_typing.py and phalkethoh_mm.py contain no http(s)://, figshare://,
      zenodo://, or hf:// literals; COORDINATE values remain
      dataset:espaloma/zinc-typing@1 and
      dataset:espaloma/phalkethoh-mm-small@1 respectively.
    status: pending
out_of_scope:
  - public resolve and user-facing docs (chain 06)
  - FrameCollection or new collection types
  - Espaloma science, units, or convert-script conversion
  - returning molpy.Trajectory from load()
---

# Acceptance — python-native-dataset-protocol-05-mm

两个 MM 定义类成为 `@dataset` 定义；`load()` 交出 `InMemoryDataset`；`MoleculeSplit` 只对集合工作。
