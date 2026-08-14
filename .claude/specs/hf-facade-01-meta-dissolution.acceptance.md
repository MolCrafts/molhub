---
slug: hf-facade-01-meta-dissolution
criteria:
  - id: ac-001
    summary: Targets, MetaCodec and write_meta no longer exist anywhere
    type: code
    pass_when: |
      `_meta.py` and `meta.py` are absent from src/molhub/dataset/, and an
      identifier-boundary-aware scan (regex \bTargets\b / \bMetaCodec\b /
      \bwrite_meta\b(?!data), excluding *.egg-info/) over src/, tests/,
      scripts/ and regressions/ finds no hit — `write_metadata`
      (DerivedLayout's unrelated conveyor API) and `TargetSchema` /
      `TargetDeclaration` must not match, and the universal_class_i.py
      docstring coincidence is reworded rather than carved out.
    status: pending
  - id: ac-002
    summary: Every adapter writes graph scalars through frame.meta directly
    type: code
    pass_when: |
      Each of water_les.py, threebpa.py, revmd17.py, csv_dataset.py, molrec.py,
      zinc_typing.py, phalkethoh_mm.py, qm9.py and themol.py writes graph-level
      values with `frame.meta = {...}` or `frame.meta.update({...})` and imports
      nothing from a molhub meta module.
    status: pending
  - id: ac-003
    summary: Adapter unit tests pass on their mirrored paths alone
    type: runtime
    pass_when: |
      `uv run pytest tests/test_dataset -v` and `uv run pytest tests/test_conveyor -v`
      both pass, and tests/test_dataset/test__meta.py no longer exists.
    status: pending
  - id: ac-004
    summary: Transforms stay pure and keep their published numerics
    type: runtime
    pass_when: |
      tests/test_dataset/test_transforms.py asserts AtomicDress baselines and
      residuals, the hartree->eV conversion and ConstantLabel output against the
      same literals as before the change, and asserts the input frame's meta is
      unchanged after each execute().
    status: pending
  - id: ac-005
    summary: Existing regressions re-run green with no golden moved
    type: runtime
    pass_when: |
      `python regressions/molix-data-dissolution-05-molhub-reception.py`,
      `python regressions/mm-param-val-01-molhub-contract.py` and
      `python regressions/streaming-data-tiers-03-conveyor-03-prepare.py` all exit 0,
      and their diffs versus the previous revision touch only import and call-site
      lines - no numeric literal changes.
    status: pending
  - id: ac-006
    summary: Meta-dissolution regression reproduces the transform goldens
    type: runtime
    pass_when: |
      `python regressions/hf-facade-01-meta-dissolution.py` exits 0, reading and
      writing frame.meta through the public molhub.dataset surface only, and
      reproduces the hard-coded AtomicDress baselines, unit-conversion factor and
      ConstantLabel value embedded as literals in the script.
    status: pending
---

# Acceptance criteria

ac-001/ac-002 are the deletion contract — no wrapper survives anywhere, and no
adapter routes meta through anything but the frame. ac-004 and ac-005 are the
value-preservation bar: this sub-spec changes *how* meta is written, never
*what* — a moved numeric golden is a defect, not a rebase. ac-006 is the
public-API witness.
