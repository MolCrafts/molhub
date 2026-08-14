---
slug: streaming-data-tiers-03-conveyor-03-prepare
criteria:
  - id: ac-001
    summary: No partial sampling unit can reach a block writer
    type: code
    pass_when: |
      `uv run pytest tests/test_conveyor/test_prepare.py -v` is green, including a
      test where the injected fake BlockWriterLike records every append_unit
      argument and asserts: every recorded object is a RawUnit; each recorded
      unit's n_frames equals its source record's frame count; the multiset of
      recorded unit keys equals the fixture's record keys with no key twice; and
      an AST assertion that `src/molhub/conveyor/prepare.py` calls exactly one
      writer ingestion method, `append_unit`, with no frame-level path.
    status: pending
  - id: ac-002
    summary: Mixed-split shard fans out into split-pure sealed blocks
    type: code
    pass_when: |
      A fixture shard of 5 records over 3 identities routed train/val/test
      produces exactly 3 entries in PreparedBlocks.blocks with splits
      {"train","val","test"} and the pinned per-split unit counts; each fake
      writer was constructed with exactly one `split=` value; no append_unit call
      carries a split argument; and a record whose identity is absent from
      `split_of` raises UnroutableUnitError naming that identity and unit key
      without sealing any block under a default split.
    status: pending
  - id: ac-003
    summary: Size fan-out opens a new block but never splits a unit
    type: code
    pass_when: |
      With `max_block_bytes=1`, N single-split units yield N sealed roots named
      `<name>-<split>-000`, `-001`, … in order; every PreparedBlock has
      unit_count == 1; the concatenation of recorded units equals the input
      records in order; and no unit key appears in two blocks.
    status: pending
  - id: ac-004
    summary: PreparedBlocks carries complete, verified READY evidence
    type: code
    pass_when: |
      For every sealed root, PrepareJob reads `<root>/manifest.json` after seal()
      and the returned PreparedBlock carries root, split, unit_count,
      frame_count, committed_bytes and the manifest's block_digest; a manifest
      with `sealed: false`, a `format` other than "molix.block/1", or `units`
      disagreeing with the writer's unit_count raises BlockFormatError; and
      PreparedBlocks.blocks names every root the job sealed (length equals the
      fan-out count).
    status: pending
  - id: ac-005
    summary: Conveyor package imports clean in a torch-free base environment
    type: code
    pass_when: |
      `uv run pytest tests/test_conveyor/test_layering.py -v` is green: an AST
      walk over every `src/molhub/conveyor/*.py` finds no module-scope import of
      `torch` or any `molix*` module; no module under `src/molhub/dataset/`
      imports `molhub.conveyor`; and `python -c "import molhub.conveyor.prepare"`
      succeeds in an environment with neither torch nor molnex installed.
    status: pending
  - id: ac-006
    summary: numpy declared as a base dependency; prepare extra declared
    type: code
    pass_when: |
      `pyproject.toml` lists `numpy` in `[project] dependencies` and a
      `prepare` entry under `[project.optional-dependencies]`, both asserted by a
      test that parses pyproject.toml with `tomllib`; `rg -n "import numpy"
      src/molhub` shows every importing module covered by that declaration.
    status: pending
  - id: ac-007
    summary: Encoder goldens pinned per THEMol record type, units unchanged
    type: code
    pass_when: |
      `uv run pytest tests/test_conveyor/test_encoder.py -v` is green: for
      HessianRecord, EnergyForceTrajectory and TorsionProfile the produced
      RawUnit's column names, dtypes (`<i2` atom_Z, `<i4` valence and
      mol_target_torsion_atoms, `<f4` frame columns), shapes and values equal
      hard-coded literals; the values are the fixture's numbers unchanged in Å /
      kcal mol⁻¹ / kcal mol⁻¹ Å⁻¹; a zero-bond molecule yields empty (not
      missing) bond columns; and a ragged trajectory, a bond block without an
      integer order column, and an MBISRecord raise IncompleteRecordError /
      IncompleteRecordError / UnsupportedRecordError respectively.
    status: pending
  - id: ac-008
    summary: One molecular-identity rule serves routing and split production
    type: code
    pass_when: |
      `THEMolUnitEncoder.identity(<fixture mapped_isomeric_smiles>)` equals the
      pinned blake2b-128 hex literal in the test, and
      `rg -n "blake2b" src/ scripts/` shows exactly one implementation, with
      `scripts/build_class1_splits.py` importing it rather than redefining it.
    status: pending
  - id: ac-009
    summary: Regression reproduces fan-out goldens, gated real-writer leg included
    type: runtime
    pass_when: |
      `uv run python regressions/streaming-data-tiers-03-conveyor-03-prepare.py`
      exits 0 in the base environment: it asserts `"torch" not in sys.modules`
      after importing molhub.conveyor.prepare, then reproduces the hard-coded
      goldens (three sealed roots, their names, per-split unit and frame counts,
      each input record appended exactly once and whole) through the fake writer;
      and, when MOLNEX_SRC points at a molnex checkout's src/ so
      `molix.store.block` imports, its second leg writes real sealed blocks via
      MolnexBlockWriter and asserts through BlockReader the same unit counts, one
      split per manifest, and frame_pos equal bit-for-bit to the encoder's
      float32 arrays. Without MOLNEX_SRC the leg prints a SKIP line and the exit
      code stays 0. No third-party oracle runs to produce any value.
    status: pending
  - id: ac-010
    summary: Boundary decisions documented where the code lives
    type: docs
    pass_when: |
      `src/molhub/conveyor/prepare.py`'s module docstring names the Option-A
      lazy-import ruling, the single import site, and the three rejected
      alternatives (entry-point plugin, subprocess converter, seam inversion);
      `src/molhub/conveyor/encoder.py`'s docstring names why the Cartesian
      Hessian is not encoded (no routable column space in molix.block/1; Hessian
      core is hot tier per strategy § 6) and the successor that owns it; and the
      `prepare` extra in pyproject.toml carries a comment naming molnex's
      non-PyPI status and the MOLNEX_SRC escape hatch.
    status: pending
---

# Acceptance criteria

**ac-001 / ac-003 (unit integrality)** are the I2 pair. ac-001 proves nothing
smaller than a unit is ever handed to a writer; ac-003 proves the byte-ceiling
policy cannot become a reason to cut one. Both are checked against the injected
fake, never against molnex.

**ac-002 / ac-004** are the I7 + I5 pair: split purity is structural (one
`split=` per writer, none on `append_unit`), and READY is witnessed only by a
sealed manifest whose fields the job verifies before reporting them.

**ac-005 / ac-006** protect the environment contract this spec extends from
`molix-data-dissolution-05-molhub-reception` ac-006: the base install stays
torch-free and honest about what it imports. ac-006 closes the pre-existing
undeclared-numpy defect named in the spec's Iron-law section.

**ac-007 / ac-008** pin the producer-side numbers: unchanged THEMol units, exact
float32 goldens, and a single molecular-identity rule shared with split
production.

**ac-009** is the only criterion that may exercise real molnex, and only through
the `MOLNEX_SRC` gate; its ungated half must pass on a machine that has never
installed torch.
