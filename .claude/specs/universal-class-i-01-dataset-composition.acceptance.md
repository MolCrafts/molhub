---
spec: universal-class-i-01-dataset-composition
slug: universal-class-i-01-dataset-composition
created: 2026-08-18
criteria:
  - id: ac-001
    summary: CollectionRole exposes active with default True
    type: code
    pass_when: |
      CollectionRole in src/molhub/dataset/universal_class_i.py is a frozen
      dataclass with active: bool = True after derived; existing keyword
      construction without active still works and yields active is True.
    status: pending
  - id: ac-002
    summary: source_coordinates lists only active roles
    type: code
    pass_when: |
      MultiSourceDatasetCollection.source_coordinates folds coordinates from
      roles with active True only, in role order, without duplicates;
      active_roles equals that filtered tuple.
    status: pending
  - id: ac-003
    summary: v0 active roles are train and validation
    type: code
    pass_when: |
      Class1Universal2026().load().active_roles names are exactly
      ("train", "validation") in that order.
    status: pending
  - id: ac-004
    summary: train pins omol25-small as derived QM E/F
    type: code
    pass_when: |
      load().role("train") has source_coordinates
      ("dataset:molcrafts/omol25-small@1",), derived True, active True,
      TargetSchema qm energy+forces, and reference_method ωB97M-V/def2-TZVPD.
    status: pending
  - id: ac-005
    summary: validation pins phalkethoh-mm-small as MM
    type: code
    pass_when: |
      load().role("validation") has source_coordinates
      ("dataset:espaloma/phalkethoh-mm-small@1",), active True, TargetSchema
      mm including mm_energy, and a classical-MM reference_method (not DFT).
    status: pending
  - id: ac-006
    summary: THEMol roles stay declared and inactive
    type: code
    pass_when: |
      role("equilibrium"), role("torsion"), role("off-equilibrium"), and
      role("electrostatic") succeed with active False; role("intermolecular")
      raises KeyError.
    status: pending
  - id: ac-007
    summary: v0 resolve-set omits THEMol coordinates
    type: code
    pass_when: |
      load().source_coordinates equals
      ("dataset:molcrafts/omol25-small@1",
       "dataset:espaloma/phalkethoh-mm-small@1")
      and contains none of themol/hessian@1, themol/torsion-scan@1,
      molcrafts/themol-relax-diverse@1, or themol/mbis@1.
    status: pending
  - id: ac-008
    summary: load() performs no fetch or filesystem IO
    type: runtime
    pass_when: |
      tests/test_dataset/test_universal_class_i.py proves Class1Universal2026()
      and load() succeed when Molhub.fetch is replaced by an assertion failure.
    status: pending
  - id: ac-009
    summary: Unknown role KeyError lists available names
    type: code
    pass_when: |
      load().role("flat-pool") raises KeyError whose message contains
      "Available:" and the declared role names including train and validation.
    status: pending
  - id: ac-010
    summary: Train QM and validation MM schemas stay disjoint
    type: scientific
    evaluator_hint: "path: tests/test_dataset/test_universal_class_i.py"
    pass_when: |
      train.target_schema includes energy/forces in qm and does not include
      mm_energy; validation.target_schema includes mm_energy in mm and has
      empty qm; both roles declare Å coordinates and kcal/mol-family energy
      units.
    status: pending
  - id: ac-011
    summary: Regression reproduces the hard-coded v0 role map
    type: runtime
    pass_when: |
      regressions/universal-class-i-01-dataset-composition.py exits 0 and
      asserts the hard-coded literals coordinate
      dataset:molcrafts/class1-universal-2026@1, active names
      train/validation, sources omol25-small@1 and phalkethoh-mm-small@1,
      inactive THEMol role names, and source_coordinates containing no
      hessian/torsion-scan/relax/mbis; no third-party oracle at runtime.
    status: pending
  - id: ac-012
    summary: Class docstring states v0 versus deferred THEMol
    type: docs
    pass_when: |
      Class1Universal2026 docstring (Google style, with units) states that
      v0 active roles are OMol25-small train and PhAlkEthOH-MM validation,
      that load() is zero-IO, and that THEMol roles are declared but not a
      resolve gate.
    status: pending
out_of_scope:
  - THEMol source adapters and shard/manifest scripts
  - Materializing hessian, torsion-scan, relax, or MBIS for v0
  - class1-benchmark and later OMol25 intermolecular / OPoly26 subsets
  - Molexp losses, metrics, FrameDataset/DataModule wiring, and MolNex library changes
  - Conveyor/loader/CLI refactors
---

# Acceptance — universal-class-i-01-dataset-composition

Done 的意思是：`Class1Universal2026.load()` 仍是零 IO 的角色清单，但 v0 **解析集**只有 OMol25-small（DFT E/F）和 PhAlkEthOH-MM-small（经典 `mm_energy`）；THEMol 四类坐标可以按名查到、却进不了 `source_coordinates`。训练/验证如何组 batch 不在本契约里。

## AC-001 — CollectionRole.active

字段默认 `True`，放在 `derived` 之后。现有只传 `derived=` 的构造不得被破坏。这是延期角色能活在同一类型里的最小推广。

## AC-002 — source_coordinates 只看 active

`source_coordinates` 是 v0 物化清单。inactive 角色的坐标必须从这里消失，否则「不作为解析门槛」只是文档。`active_roles` 与该过滤一致。

## AC-003 — 活跃名

公开活跃名就是 `train` 与 `validation`，顺序固定。不要再把 v0 训练叫做 `intermolecular`。

## AC-004 / AC-005 — 两条钉死的源

train 必须是已有派生坐标 `dataset:molcrafts/omol25-small@1`（4M ∩ Neutral singlet ≤32 有机 Z，eV→kcal/mol，推断键），schema 走 QM。validation 必须是 `dataset:espaloma/phalkethoh-mm-small@1`，schema 走 MM `mm_energy`，reference 不得写成 DFT。

## AC-006 / AC-007 — 远期仍在、门槛已撤

`role("electrostatic")` 等仍成功且 `active is False`，这样不删叙事、也不逼 conveyor 夹具改层。`source_coordinates` 是那道硬门：四条 THEMol 坐标不得出现。`intermolecular` 不再是本集合角色。

## AC-008 / AC-009 — 既有模式

`load()` 继续零 IO；未知名 `KeyError` 列出 Available 名。新代码必须读起来像旧的 `Class1Universal2026`。

## AC-010 — QM 与 MM 不可混为一谈

这是本 spec 能在集合层钉死的科学合同：两边 family 与能量键名不同。按分子中心化 MSE/MAE 属于 Molexp，不在此验收。

## AC-011 — 回归

`regressions/universal-class-i-01-dataset-composition.py` 用字面量锁住角色图。禁止运行时导入 ASE / espaloma / 其它第三方 oracle。

## AC-012 — 文档

类文档必须说清 v0 活跃集、单位、以及 THEMol 延期不是解析门槛，避免下一轮又把 hessian 写回 required。
