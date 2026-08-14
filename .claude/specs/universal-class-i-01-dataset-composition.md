---
title: Universal Class-I FF — Dataset Composition Specification
status: approved
created: 2026-08-13
chain: universal-class-i-dataset
owners: [molhub]
---

# Universal Class-I FF — Dataset Composition

## 1. Goal

The training dataset must not be constructed as one giant pool of
interchangeable molecular configurations. Different datasets constrain
different parts of the Class-I potential:

\[
\Theta_{\mathrm{MM}} =
\{r_0,k_b,\theta_0,k_\theta,V_{\mathrm{torsion}},q,\sigma,\epsilon\}.
\]

The dataset collection is therefore a multi-source training collection. Every
source has a declared physical role, provenance, target schema, sampling
policy, and split policy. Sources are combined at the training-task level, not
by concatenating all frames into an undifferentiated dataset.

The initial MolHub collection is:

**`molcrafts/class1-universal-2026@1`**

```text
class1-universal-2026
├── equilibrium
│   └── themol/hessian@1
├── torsion
│   └── themol/torsion-scan@1
├── off-equilibrium
│   ├── themol/hessian-relax
│   └── themol/torsion-relax
├── electrostatics
│   └── themol/mbis@1
├── intermolecular
│   └── selected OMol25
└── polymer
    └── OPoly26                 # later specialization
```

## 2. Core dataset: THEMol

THEMol supplies the majority of the first universal Class-I training data. It
is divided into logically distinct task sources.

### 2.1 Equilibrium — `themol/hessian@1`

Use the complete or nearly complete Hessian molecular set.

Primary targets:

- optimized geometry;
- equilibrium bond lengths and angles;
- Hessian / curvature information;
- equilibrium energy and forces where appropriate.

Primary parameters constrained:

\[
r_0,\quad \theta_0,\quad k_b,\quad k_\theta.
\]

This source defines local equilibrium structure and stiffness. It receives
high sampling priority even though it has fewer configurations than relaxation
sources.

## 3. Torsion — `themol/torsion-scan@1`

Use THEMol TorsionScan as the principal torsional source.

Primary targets:

- relative torsion energy;
- barrier heights;
- minimum positions;
- conformer ordering;
- complete profile shape.

Primary parameters constrained are the Fourier coordinates
\(\{a_n,b_n\}_{n=1}^{N_{\max}}\).

The training object is a complete torsion profile, not an individual frame.
MolHub must preserve this hierarchy and keep every scan group intact:

```text
molecule
└── torsion scan
    ├── angle
    ├── geometry
    ├── energy
    └── scan identity
```

## 4. Off-equilibrium — derived diverse relaxation source

Raw sources:

- `themol/hessian-relax`
- `themol/torsion-relax`

Do not use all billions of relaxation configurations. Create:

**`molcrafts/themol-relax-diverse@1`**

The initial target is **20–30 million configurations**. A later larger version
may contain approximately 50 million configurations.

### 4.1 Sampling relaxation frames

Sampling must be stratified by:

- molecular identity;
- chemical environment;
- relative energy and force magnitude;
- bond and angle distortion;
- torsion angle;
- optimization progress;
- rare elements;
- molecular size.

Aggressively remove consecutive, highly correlated optimization frames. The
objective is to cover the accessible PES, not to reproduce optimizer
trajectories frame by frame.

### 4.2 HessianRelax / TorsionRelax balance

The initial 20–30M subset starts near:

```text
40% HessianRelax
60% TorsionRelax
```

Coverage analysis may change this ratio. TorsionRelax starts higher because
torsional and conformational error is expected to be a major Class-I limit.

## 5. Electrostatics — `themol/mbis@1`

Use the complete available MBIS subset where practical.

Targets may include:

- atomic charges, dipoles, and quadrupoles;
- molecular dipole;
- atomic volume and other MBIS descriptors.

The exported Class-I model ultimately uses point charges \(q_i\), but the
encoder should be supervised by richer electronic information. This source
remains physically separate from B3LYP valence data because its electronic
structure reference may differ. It is a separate task, not another energy
dataset.

## 6. THEMol v0 composition

The first universal intramolecular collection is approximately:

```text
THEMol Hessian          ~3.1M equilibrium structures
THEMol TorsionScan      up to ~94M scan configurations
THEMol Relax Diverse    ~20–30M selected configurations
THEMol MBIS             ~3.1M electrostatic structures
```

Raw counts must not determine sampling probability. In particular, the
TorsionScan frame count must not overwhelm other physical targets.

## 7. Handoff to Molexp

MolHub exposes the physical roles and preserves each role's hierarchical
sampling unit. It does **not** choose task probabilities, curriculum stages,
batch sizes, model dimensions, optimizers, hardware, or production duration.

Those run-specific values live only in the versioned Molexp experiment. The
current v0 authority is `universal-class-i-v0-calibration-gh200`, which records
the Stage A/B/C mixtures supplied with this dataset specification. MolNex
remains unaware of all concrete source coordinates.

## 9. Add OMol25 selectively

OMol25 must not be blindly appended to THEMol. Its initial role is chemical
coverage and intermolecular supervision. Create derived MolHub subsets:

```text
omol25/
├── molecular-diverse
├── intermolecular
├── solvated
└── charged
```

Prioritize **`omol25/intermolecular@1`** and
**`omol25/molecular-diverse@1`** for the first Class-I extension.

## 10. OMol25 molecular-diverse

Select several million to tens of millions of representative structures by
diversity in:

- atom embeddings or graph fingerprints;
- elements and functional groups;
- formal charge;
- ring chemistry;
- molecule size.

Do not sample OMol25 uniformly. Its role is coverage, not repetition of common
organic chemistry.

## 11. OMol25 intermolecular

Prioritize dimers, molecular complexes, explicit solvent, electrolyte-like
contacts, ion–molecule interactions, hydrogen bonding, and
dispersion-dominated interactions. Where available, deliberately sample the
repulsive region, equilibrium region, and attractive tail of interaction
distance curves.

## 12. Do not blindly mix QM levels

THEMol and OMol25 use different reference electronic-structure methods. Their
absolute energies must not be treated as one common scale.

```text
Shared Chemical Encoder
├── THEMol physical losses
└── OMol25 physical losses
```

Use source-aware targets, normalization, losses, and task sampling. THEMol is
the canonical reference for intramolecular Class-I parameterization; OMol25
adds coverage and intermolecular information.

## 13. UniversalClassI-v1 collection

The v1 MolHub collection adds the versioned OMol25 molecular-diverse and
intermolecular roles. Their batch probabilities belong to the consuming
Molexp experiment and are not fields of the MolHub collection.

## 14. Polymer data: OPoly26

Do not heavily mix OPoly26 into initial universal training. First train
**UniversalClassI**, then specialize **UniversalClassI-Poly** with OPoly26 so
the universal representation is not disproportionately biased toward polymer
structures.

## 15. Polymer specialization handoff

The polymer collection identifies OPoly26 and the universal replay sources.
Fine-tuning probabilities and replay schedules live in the corresponding
Molexp specialization experiment, not in MolHub or MolNex.

## 16. Molecular graph weighting

Raw conformation count must not determine molecular importance. Use:

```text
task → molecule / scan → conformations
```

Never use a flat random configuration draw across the complete collection. A
molecule with 1,000 relaxation frames must not automatically receive 100 times
the influence of one with 10 frames.

## 17. Rare chemistry rebalancing

Track and rebalance coverage by element, formal charge, aromatic environment,
ring size, local graph pattern, SMARTS prototype, and molecule size. The goal
is a useful distribution over chemical environments, not a uniform molecular
distribution.

## 18. Deduplication across datasets

MolHub must identify overlapping molecules across THEMol, OMol25, OPoly26, and
future sources. Exact molecular graph duplicates should share a global
molecular identity. Cross-source deduplication must precede final split
assignment to prevent the same molecule appearing in train and test through
different sources.

## 19. Split before configuration sampling

The required order is:

```text
normalize molecular graphs
→ assign global molecular identity
→ train / validation / test split
→ sample configurations
```

All structures of one molecular identity remain in one split. Never sample
configurations first and randomly split frames afterward.

## 20. Clean, frozen validation collections

The universal test collection is not a random 10% slice. Maintain separately
versioned, frozen evaluation collections:

```text
validation/
├── random-molecule
├── scaffold-holdout
├── environment-holdout
├── rare-element
├── torsion
├── high-energy
└── intermolecular
```

They must not be changed casually between model releases.

## 21. MolHub structure

```text
molcrafts/class1-universal-2026@1
├── equilibrium
│   └── themol/hessian@1
├── torsion
│   └── themol/torsion-scan@1
├── off-equilibrium
│   └── molcrafts/themol-relax-diverse@1
├── electrostatic
│   └── themol/mbis@1
├── foundation
│   ├── omol25/molecular-diverse@1
│   └── omol25/intermolecular@1
└── validation
    └── molcrafts/class1-benchmark@1
```

OMol25 components may be omitted in v0.

## 22. Release sequence

### Dataset collection v0 — THEMol only

Hessian + TorsionScan + 20–30M diverse Relax + MBIS. Purpose: universal
intramolecular Class-I.

### Dataset collection v1 — THEMol + selected OMol25

v0 + OMol25 molecular-diverse + OMol25 intermolecular. Purpose: broader
chemistry and improved nonbonded potential.

### Dataset collection v1-poly

v1 + OPoly26 through domain-adaptation sampling rather than full replacement.
Purpose: polymer specialization.

## 23. Key principle

Do not describe this as merely “130 million molecular configurations.” The
scientifically meaningful description is:

> A task-balanced combination of equilibrium/Hessian, torsional,
> off-equilibrium, electrostatic, and intermolecular datasets, each selected to
> identify a different component of the Class-I potential.

\[
\boxed{
\text{Hessian} + \text{Torsion PES} +
\text{diverse off-equilibrium E/F} +
\text{electrostatics} + \text{intermolecular interactions}
}
\]

Every component preserves its provenance, physical targets, sampling policy,
and MolHub version. Raw size never determines scientific weight.
