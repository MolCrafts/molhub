---
slug: universal-class-i-01-dataset-composition
criteria:
  - id: ac-001
    summary: MolHub v0 collection is task-structured and versioned
    type: data
    pass_when: |
      molcrafts/class1-universal-2026@1 resolves equilibrium, torsion,
      off-equilibrium, and electrostatic roles to versioned sources; each role
      exposes provenance, target schema, units, group identity, and split.
    status: pending
  - id: ac-002
    summary: THEMol source identities and native grouping are preserved
    type: data
    pass_when: |
      themol/hessian@1, themol/torsion-scan@1, and themol/mbis@1 are registered.
      Torsion frames preserve molecule_id, scan_id, angle, geometry, energy,
      and complete scan membership; Hessian and MBIS targets remain distinct.
    status: pending
  - id: ac-003
    summary: diverse relaxation derivation is reproducible
    type: scientific
    pass_when: |
      molcrafts/themol-relax-diverse@1 contains 20–30M configurations selected
      reproducibly from HessianRelax/TorsionRelax near 40:60, with stratification
      and correlation pruning documented by coverage artifacts.
    status: pending
  - id: ac-005
    summary: global identity, deduplication, and split precede sampling
    type: data
    pass_when: |
      Molecular graphs receive global identities across sources; cross-source
      duplicates cannot cross splits; all conformations/scans of one identity
      stay together; split assignment occurs before conformation subsampling.
    status: pending
  - id: ac-006
    summary: frozen benchmark collection covers required holdouts
    type: scientific
    pass_when: |
      molcrafts/class1-benchmark@1 versions random-molecule, scaffold,
      environment, rare-element, torsion, high-energy, and intermolecular
      evaluations independently of the mutable training mixture.
    status: pending
  - id: ac-007
    summary: OMol25 additions are derived tasks with source-aware normalization
    type: scientific
    pass_when: |
      v1 uses versioned molecular-diverse and intermolecular subsets rather than
      all OMol25; THEMol/OMol25 targets retain distinct reference provenance and
      reference-method metadata.
    status: pending
---
