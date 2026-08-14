---
slug: hf-facade-02-frame-records
criteria:
  - id: ac-001
    summary: molpy Trajectory preserves per-frame meta and non-atoms blocks
    type: runtime
    pass_when: |
      tests/test_dataset/test_themol.py::TestTrajectoryRoundTrip constructs a
      Trajectory from two frames each carrying frame.meta scalars and a named
      non-atoms block, and asserts both survive indexing back out. If it fails the
      sub-spec stops and reports rather than working around it.
    status: pending
  - id: ac-002
    summary: The four record dataclasses are gone from the public surface
    type: code
    pass_when: |
      HessianRecord, EnergyForceTrajectory, TorsionProfile, MBISRecord,
      _LazyFrameSequence and _LazyAngles appear in no file under src/, and
      molhub.dataset.__all__ names none of them.
    status: pending
  - id: ac-003
    summary: A THEMol geometry record is a molpy Frame with the declared payload
    type: runtime
    pass_when: |
      THEMolHessian(...).load(...)[0] is a molpy.Frame whose "hessian" block has
      columns row/col/value with (3N)**2 rows in row-major order, and
      THEMolMBIS(...).load(...)[0] is a molpy.Frame whose atoms block carries
      atomic_charge, atomic_volume, the dipole components and the quadrupole
      components, each pinned by literal in tests/test_dataset/test_themol.py.
    status: pending
  - id: ac-004
    summary: A THEMol multi-frame record is a molpy Trajectory
    type: runtime
    pass_when: |
      THEMolTorsionScan / THEMolTorsionRelax / THEMolHessianRelax records are
      molpy.Trajectory instances whose per-frame meta carries energy plus
      torsion_angle or step_index, and whose scanned dihedral is a 1-row "scan"
      block with atomi/atomj/atomk/atoml.
    status: pending
  - id: ac-005
    summary: Encoder dispatches on record type plus declared task
    type: code
    pass_when: |
      THEMolUnitEncoder.encode contains no reference to a record dataclass, branches
      on Frame vs Trajectory only, and THEMolUnitEncoder(task="mbis") raises
      UnsupportedRecordError from __init__ naming the missing molix.block/1 routes.
    status: pending
  - id: ac-006
    summary: Dissolution changes no encoded column, dtype or block golden
    type: runtime
    pass_when: |
      `python regressions/streaming-data-tiers-03-conveyor-03-prepare.py` exits 0
      with every RawUnit column name, dtype, unit_count, frame_count and sealed
      manifest value identical to the previous revision; the diff touches record
      construction lines only.
    status: pending
  - id: ac-007
    summary: Frame-record regression reproduces the pinned record shapes offline
    type: runtime
    pass_when: |
      `python regressions/hf-facade-02-frame-records.py` exits 0 with no network and
      no molnex import, reproducing the hard-coded atom counts, hessian entry
      count, torsion angles and encoder column sets embedded as literals.
    status: pending
  - id: ac-008
    summary: The widened sample contract is recorded, not silently changed
    type: docs
    pass_when: |
      CLAUDE.md "What must never change casually" states the sample type as
      molpy.Frame or molpy.Trajectory and cites the 2026-08-15 operator note, and
      src/molhub/dataset/protocol.py's Sample alias and docstring agree with it.
    status: pending
---

# Acceptance criteria

ac-001 is the D3 gate — probed PASS on 2026-08-15, pinned permanently here so a
molpy regression cannot silently break the record model. ac-006 is the
value-preservation bar for the encoder: dissolution changes the record's
container, never the encoded bytes. ac-008 makes the widened `Sample` contract
a recorded amendment of a never-change-casually bullet, per the operator note.
