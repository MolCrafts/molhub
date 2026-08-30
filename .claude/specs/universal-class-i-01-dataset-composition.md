---
title: Universal Class-I v0 数据集组成（OMol25 训练 / PhAlkEthOH 验证）
status: approved
created: 2026-08-13
revised: 2026-08-20
grilled: true
chain: universal-class-i-dataset
owners: [molhub]
---

# Universal Class-I v0 数据集组成（OMol25 训练 / PhAlkEthOH 验证）

## Summary

MolHub 集合 `dataset:molcrafts/class1-universal-2026@1` 的 v0 活跃角色改为「OMol25-small 训练、PhAlkEthOH-MM 验证」：`Class1Universal2026.load()` 零 IO 返回的解析/物化集合只含 `dataset:molcrafts/omol25-small@1` 与 `dataset:espaloma/phalkethoh-mm-small@1`，不再把 THEMol hessian / torsion-scan / relax / mbis 当作 v0 门槛；验证坐标不得进入训练。THEMol 与后续 OMol25 分子间 / OPoly26 叙事仍保留为未激活角色与远期路线，供 v1 再打开，但不阻塞本版解析。训练损失与验证指标由 Molexp 实验拥有；MolNex 库保持与具体坐标无关。

## Domain basis

Class-I 势能按 Wang 2022 Appendix A 的加和式，在 OpenMM real 单位（能量 kcal/mol，长度 Å，力 kcal/mol/Å）下书写：

\[
U_{\mathrm{MM}}
= U_{\mathrm{bond}} + U_{\mathrm{angle}} + U_{\mathrm{torsion}} + U_{\mathrm{nb}},
\qquad
\Theta_{\mathrm{MM}}
= \{r_0,k_b,\theta_0,k_\theta,V_{\mathrm{torsion}},q,\sigma,\epsilon\}.
\]

键与角为谐波 \( \tfrac12 k (x-x_0)^2 \)；二面角为 OpenMM / AMBER `PeriodicTorsion`

\[
U_{\mathrm{torsion}} = \sum k\bigl[1+\cos(n\phi-\gamma)\bigr].
\]

OMol25 是 ωB97M-V/def2-TZVPD **DFT 总能**（eV）与力（eV/Å），不是经典 MM。换算

\[
E_{\mathrm{kcal}} = 23.06055\, E_{\mathrm{eV}},
\qquad
F_{\mathrm{kcal}} = 23.06055\, F_{\mathrm{eV/Å}}.
\]

**molhub 不做单位换算**（operator decision 2026-08-20，见 notes
`mol:note:topic:native-units`）：数据集如实记录原生单位（OMol25 为 eV /
eV/Å）并在角色 `units` 里声明；上式换算由消费方在训练边界完成（molnex 走
`molix.units`，或 in-tree `UnitConvert` transform）。PhAlkEthOH 的
`mm_energy` 是 **经典 MM 势能**（原生 kcal/mol；原生 DGL `u_ref` 已在转换树
中变为 kcal/mol），零点与量级都不是 DFT 总能。

**禁止**把 OMol25 DFT 总能与 `mm_energy` 放进同一个 MSE。训练只对 OMol25：能量必须 **按分子减均值** 再 MSE，并另加力 MSE；\( F = -\mathrm{d}E/\mathrm{dpos} \)。验证只在 seed-2666 holdout 分子上，对训练好的 Class-I \(U_{\mathrm{MM}}\) 与 `mm_energy` 做 **按分子中心化后的 MAE（kcal/mol）**。训练路径永不读 `mm_energy`。OMol25 E/F 不能唯一确定 \(\{q,\sigma,\epsilon\}\)；v0 冻结或 legacy-init LJ，电荷若训必须有单独 charge loss。不把 THEMol / Hessian / torsion-scan / relax / MBIS 纳入 v0，与这一可辨识性缺口一致。

Wang et al. Chem. Sci. 2022 DOI 10.1039/D2SC02739A / arXiv:2010.01196 — Espaloma; QM fit uses per-molecule mean centering; MM-mimic and QM-fit are separate experiments; freeze LJ on QM fits.

Levine et al. arXiv:2505.08762 v2 — OMol25 ωB97M-V/def2-TZVPD; energy eV, forces eV/Å; no Hessian/MBIS as product.

OpenMM User Guide standard forces — ½k harmonic; PeriodicTorsion.

Never one MSE over DFT totals and mm_energy.

Val = per-molecule-centered MAE of applied Class-I vs mm_energy.

## Design

本 spec 只改 MolHub 集合声明，不新造集合类型，不改 THEMol 源适配器，不实现训练循环。拥有类型仍是 `CollectionRole`、`MultiSourceDatasetCollection`、`Class1Universal2026`。`load()` 继续零 IO：返回不可变角色表，由调用方按坐标自行 `fetch` / 打开。训练混合、batch、损失、指标属于 Molexp；MolNex 的 `FrameDataset` / `DataModule` 只作为实验侧已有原语被点名，本仓不实现、不接线。

### `CollectionRole.active`

给现有冻结数据类增加 `active: bool = True`（放在已有 `derived` 之后，保持默认值在末尾）。`active=True` 的角色进入 v0 解析/物化集；`active=False` 的角色仍可通过 `role(name)` 按名取出（远期叙事与现有 conveyor 夹具对 `electrostatic` / `torsion` 的查找继续成立），但 **不得** 出现在 `source_coordinates` 里，因此遍历解析集不会去要 hessian / torsion-scan / relax / mbis。禁止另起 `DeferredCollection` 或第二套集合类。未知名仍按现有模式 `KeyError`，消息列出全部已声明角色名。

`MultiSourceDatasetCollection` 增加只读 `active_roles`（`tuple` 过滤 `role.active`）。现有 `source_coordinates` 改为只折叠 **active** 角色的坐标、保序去重；`role()` 仍在全部 `roles` 上查找。

### v0 `Class1Universal2026.load()` 角色表

活跃角色只有两个，且必须排在声明表前部：

| name | source | schema / family | units（原生，如实记录） | sampling_unit | derived | active |
|---|---|---|---|---|---|---|
| `train` | `dataset:molcrafts/omol25-small@1` | graph `energy` + atom `forces`；`qm` | `eV`，`eV/angstrom`，坐标 Å | `molecule` | True | True |
| `validation` | `dataset:espaloma/phalkethoh-mm-small@1` | graph `mm_energy` + 可选 atom `forces`；`mm` | `kcal/mol`，`kcal/mol/angstrom`，坐标 Å | `molecule` | False | True |

`train` 的派生契约已经由 `OMol25Small` / `OMol25SmallFilter` 实现，本 spec 只声明、不重写：源是 `dataset:fairchem/omol25@1` 的 role `4m`；保留 Neutral、singlet、\(n_{\mathrm{atoms}}\le 32\)、有机 Z；标签保持原生 eV / eV/Å（换算归消费方）；推断键。`reference_method` 为 `ωB97M-V/def2-TZVPD`。

`validation` 复用 `PhalkethohMMDataset`：173 分子 × 100 构象，`mm_energy` 已是 kcal/mol，分子级 80:10:10、seed 2666。集合钉的是整条坐标，不在 `load()` 里选 split；Molexp 只许用该坐标的 holdout 分子做验证，**整条 PhAlkEthOH 坐标不得进入训练 loader**（包括其 published `train` 分片，因为标签是 MM 而不是 DFT）。`reference_method` 必须写明经典 MM，不得写成 DFT。

单位字符串跟各自源模块已有拼写走（OMol25-small 的 `eV` / `eV/angstrom`，PhAlkEthOH 的 `kcal/mol`），集合层不发明第三套拼写。

### 未激活但仍声明的 THEMol 角色

不要删除远期物理角色。`load().roles` 在两个活跃角色之后继续声明，全部 `active=False`：

- `equilibrium` → `dataset:themol/hessian@1`（分子；Hessian / 平衡几何）
- `torsion` → `dataset:themol/torsion-scan@1`（完整 torsion profile）
- `off-equilibrium` → `dataset:molcrafts/themol-relax-diverse@1`（派生；分子再选构象）
- `electrostatic` → `dataset:themol/mbis@1`（MBIS；壳层不是 per-atom，现有 docstring 约束保留）

这些坐标 **不是** v0 的 `source_coordinates`，因此不是解析/物化门槛。THEMol 适配器（`src/molhub/dataset/themol.py` 及 generate/audit 脚本）本 spec 不动。当前误把 `omol25-small` 标成 `intermolecular` 的活跃角色删除：v0 的 OMol25-small 是训练用小分子 DFT E/F，不是分子间专项；真正的 `omol25/intermolecular@1` 等坐标尚未存在，只留在下面的远期树里。

### 远期叙事（不进 v0 `source_coordinates`）

```text
molcrafts/class1-universal-2026@1
├── train          dataset:molcrafts/omol25-small@1          # v0 active
├── validation     dataset:espaloma/phalkethoh-mm-small@1    # v0 active；禁止入训
├── equilibrium    themol/hessian@1                          # deferred
├── torsion        themol/torsion-scan@1                     # deferred
├── off-equilibrium molcrafts/themol-relax-diverse@1         # deferred
├── electrostatic  themol/mbis@1                             # deferred
├── foundation     omol25/molecular-diverse@1 + intermolecular@1   # v1
└── polymer        OPoly26                                   # v1-poly；先通用再特化
```

跨源去重、全局分子身份、先 split 再抽构象、以及独立冻结的 `molcrafts/class1-benchmark@1`（random-molecule / scaffold / environment / rare-element / torsion / high-energy / intermolecular）仍是后续版本的策略，不是 v0 门槛。v0 验证集就是 PhAlkEthOH-MM-small 的 seed-2666 holdout，不是 `class1-benchmark`。

### 实验侧交接（本仓不实现）

Molexp 用 `Class1Universal2026().load().active_roles`（或等价地只解析 `source_coordinates`）接线：train loader 只打开 OMol25-small；val loader 只打开 PhAlkEthOH-MM-small 的 holdout。损失与指标按 Domain basis。MolNex `FrameDataset` / `DataModule` 保持坐标无关，由实验脚本组合。

### Reuse decision

- reuse `Class1Universal2026` — 仍是唯一集合定义；只改 `load()` 角色表与类文档。
- generalize `CollectionRole` — 增加 `active`，让同一类型同时表达 v0 活跃角色与延期物理角色。
- generalize `MultiSourceDatasetCollection` — `source_coordinates` 只发射 active 坐标，并暴露 `active_roles`。
- reuse `OMol25Small` / `OMol25SmallFilter` — train 角色只钉其坐标与已有过滤/换算/键推断；不重写过滤器。
- reuse `PhalkethohMMDataset` — validation 角色只钉其坐标、`mm_energy` schema 与 seed-2666 分子级 split。
- reuse `FrameDataset` — 实验侧已有原语；本 spec 不改 molnex。
- reuse `DataModule` — 同上。
- new — 无。不发明新集合类型，不改 THEMol 源适配器，不把 v0 val 做成 `class1-benchmark`。

## Files to create or modify

- `src/molhub/dataset/universal_class_i.py`
- `tests/test_dataset/test_universal_class_i.py`
- `regressions/universal-class-i-01-dataset-composition.py` (new)

## Tasks

- [x] Write failing unit tests for CollectionRole, MultiSourceDatasetCollection, and Class1Universal2026 (tests/test_dataset/test_universal_class_i.py → TestCollectionRole, TestMultiSourceDatasetCollection, TestClass1Universal2026)
- [x] Generalize `CollectionRole` in src/molhub/dataset/universal_class_i.py to cover deferred physical roles via `active: bool = True`
- [x] Generalize `MultiSourceDatasetCollection.source_coordinates` in src/molhub/dataset/universal_class_i.py to emit only active-role coordinates and expose `active_roles`
- [x] Generalize `Class1Universal2026.load()` in src/molhub/dataset/universal_class_i.py so v0 active roles are `train=dataset:molcrafts/omol25-small@1` and `validation=dataset:espaloma/phalkethoh-mm-small@1`; keep THEMol physical roles with `active=False`
- [x] Add docstring per google with units in src/molhub/dataset/universal_class_i.py
- [x] Add regression example regressions/universal-class-i-01-dataset-composition.py (public API only; hard-coded goldens, no third-party runtime)
- [x] Verify against the v0 resolve-set (no hessian/torsion/relax/mbis) and disjoint QM vs MM schemas
- [x] Run full check + test suite

## Testing strategy

单元测试只放在 `tests/test_dataset/test_universal_class_i.py`，按类型镜像：`TestCollectionRole`、`TestMultiSourceDatasetCollection`、`TestClass1Universal2026`。每个测试只打一个方法。禁止在 `tests/` 里拉真实制品、网络或 Molexp 训练。

- 快乐路径：`load()` 零 IO；`active_roles` 名为 `("train", "validation")`；`source_coordinates == ("dataset:molcrafts/omol25-small@1", "dataset:espaloma/phalkethoh-mm-small@1")`；train 为派生 QM `energy`/`forces`、`reference_method` 含 `ωB97M-V/def2-TZVPD`；validation 为 MM `mm_energy`、坐标即 PhAlkEthOH-MM-small。
- 边界：`role("flat-pool")` 为 `KeyError` 且消息列出全部已声明名；`role("electrostatic")` / `role("torsion")` 仍可取到且 `active is False`；`role("intermolecular")` 不再存在；构造与 `load()` 在 `Molhub.fetch` 被替换成断言失败时仍成功。
- 域验证（硬编码）：train 的 `target_schema.qm` 含 `energy`/`forces` 且不含 `mm_energy`；validation 的 `target_schema.mm` 含 `mm_energy` 且 `qm` 为空；train 的 `units` 为原生 `eV` 族、validation 为原生 `kcal/mol` 族、坐标均为 Å。不在本仓断言训练 MAE。

回归示例 `regressions/universal-class-i-01-dataset-composition.py` 只调用公开 API：`Class1Universal2026().load()`，把上述坐标、活跃名、未激活 THEMol 名、以及 `source_coordinates` 不含 `themol/hessian` / `themol/torsion-scan` / `themol-relax-diverse` / `themol/mbis` 写成字面量断言。注释写明 tool / command / date；运行时不导入 ASE、espaloma 或第三方 oracle。换算因子 23.06055 只作为注释中的科学约定，回归不重算。

## Out of scope

- 改 `src/molhub/dataset/themol.py` 或任何 THEMol shard / manifest 生成脚本。
- 物化 hessian、torsion-scan、relax-diverse、MBIS，或把它们重新变成 v0 解析门槛。
- 新建 `molcrafts/class1-benchmark@1` 或改 v0 验证去用它。
- 派生 `omol25/molecular-diverse`、`omol25/intermolecular`、OPoly26。
- 跨源全局身份、先 split 再抽样的实现（策略保留在远期叙事）。
- Molexp 训练循环、按分子中心化 MSE / MAE、LJ 冻结、charge loss、以及 `FrameDataset` / `DataModule` 接线。
- MolNex 库代码与 molnex 侧 composition spec。
- 改 conveyor / loader / CLI 层；它们继续按名取延期角色，但 v0 物化必须走 `active_roles` / `source_coordinates`。
- 把 DFT 总能与 `mm_energy` 混进同一个损失（科学上禁止；由实验遵守，本集合只保证 schema 分离）。
