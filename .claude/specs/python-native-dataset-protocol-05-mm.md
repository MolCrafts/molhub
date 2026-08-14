---
title: 将 ZincTyping / PhalkethohMM 迁到 @dataset + load() 集合
status: approved
created: 2026-08-12
revised: 2026-08-12
grilled: true
---

# 将 ZincTyping / PhalkethohMM 迁到 @dataset + load() 集合

## Summary

调用方用短名 `ZincTyping` / `PhalkethohMM`（`*Dataset` 仍是同一对象的别名）构造**定义**，再 `load()` 得到 03 的 `InMemoryDataset`（PyTorch `Dataset`），按整数下标取 `molpy.Frame`；`import` 与构造不下载。**删除 `MolecularFrame` 与 `MoleculeSplit`**（样本就是 `molpy.Frame`；身份在 `frame.meta`，用 `Targets` 读写）。坐标仍只有 `dataset:espaloma/zinc-typing@1` 与 `dataset:espaloma/phalkethoh-mm-small@1`。`load()` 返回的集合满足 PyTorch `Dataset` 协议（`__len__` / `__getitem__`）。

## Design

本 spec 是同链 01–04 的 L3 迁移，不新造协议、集合类型或坐标。定义类负责**视图描述**（`root` / `split` / `hub`），集合负责**样本**。

### 定义类（不可索引）

| 短名 | 装饰器 | `COORDINATE` / `manifest.canonical` | 别名 |
|---|---|---|---|
| `ZincTyping` | `@dataset(name="zinc-typing", namespace="espaloma", version="1")` | `dataset:espaloma/zinc-typing@1` | `ZincTypingDataset = ZincTyping` |
| `PhalkethohMM` | `@dataset(name="phalkethoh-mm-small", namespace="espaloma", version="1")` | `dataset:espaloma/phalkethoh-mm-small@1` | `PhalkethohMMDataset = PhalkethohMM` |

类属性保持：`COORDINATE`（必须等于 `Cls.manifest.canonical`）、`TARGET_SCHEMA`、`SPLITS`。适配器内仍不得出现上游 URL 字面量。

`__init__(root, *, split=..., hub=None)` 只校验 `split` 并保存句柄：**零 IO**。去掉 `download=`。`root` 仍必填。`split` 是构造期视图：zinc 默认 `"train"`，允许 `split=None` 表示 published 顺序全集（train→val→test，`source_id == COORDINATE`）；phalkethoh 保持 `split=None` 全集。

定义类**不**实现 `__len__` / `__getitem__`。不公开 `molecule_ids` / `split_table`。不提供 `MolecularFrame` / `MoleculeSplit`。

### `load()` → 03 集合，不是 Trajectory

`load()` 是唯一定位 + 物化点，返回新的 `InMemoryDataset`。禁止返回 `molpy.Trajectory`。

定位：`root` 已是合法 payload 树则用之且**不**打 hub；否则 `ArtifactHub.fetch(COORDINATE, roles=["main"])`。不要走 02 的文件型 `Dataset.fetch()`（main 可能是目录或 zip）。Phalkethoh zip 解压留在 `load()` 内。定义类顶层不得 `import Molhub`。

`source_id`：`split is None` → `COORDINATE`；否则 → `f"{COORDINATE}#split={split}"`。

Frame 契约不变：zinc 为 `atoms.{element,number,atom_type}`、可选 Å 坐标、`bonds`、graph `molecule_id`；phalkethoh 为 Å、`mm_energy` kcal/mol、可选力、`conformer_id`。

### 没有 Frame 包装器

样本是 `Frame`。`molecule_id` / `conformer_id` 只是 `Targets(frame)` 里的 meta 键。切分用 `SubsetDataset`（对齐 `torch.utils.data.Subset`）或调用方自己的下标列表。删除 `MoleculeSplit` / `MolecularFrame` / `KNOWN_SPLIT_SCHEMES`。

### Reuse decision

- reuse `@dataset` — 装饰两个定义类
- reuse `InMemoryDataset` — `load()` 的唯一返回集合类型
- reuse `ArtifactHub` — 仅 `load()` 调用 `fetch`
- reuse `TargetSchema` / `Targets`
- reuse `SubsetDataset`（torch `Subset` 同类）
- delete `MolecularFrame` / `MoleculeSplit` / `KNOWN_SPLIT_SCHEMES`

## Files to create or modify

- `src/molhub/dataset/zinc_typing.py`
- `src/molhub/dataset/phalkethoh_mm.py`
- `src/molhub/dataset/molecular.py`
- `src/molhub/dataset/__init__.py`
- `tests/test_dataset/test_zinc_typing.py`
- `tests/test_dataset/test_phalkethoh_mm.py`
- `tests/test_dataset/test_molecular.py`
- `regressions/mm-param-val-02-zinc-typing.py`
- `regressions/mm-param-val-03-phalkethoh-mm.py`
- `regressions/python-native-dataset-protocol-05-mm.py` (new)

## Tasks

- [ ] Write failing unit tests for ZincTyping (tests/test_dataset/test_zinc_typing.py → TestZincTyping)
- [ ] Write failing unit tests for PhalkethohMM (tests/test_dataset/test_phalkethoh_mm.py → TestPhalkethohMM)
- [ ] Write failing unit tests that MolecularFrame and MoleculeSplit are gone (tests/test_dataset/test_molecular.py → TestPublicReExports)
- [ ] Implement ZincTyping and ZincTypingDataset alias in src/molhub/dataset/zinc_typing.py
- [ ] Implement PhalkethohMM and PhalkethohMMDataset alias in src/molhub/dataset/phalkethoh_mm.py
- [ ] Export ZincTyping, PhalkethohMM, and *Dataset aliases from src/molhub/dataset/__init__.py
- [ ] Delete MolecularFrame, MoleculeSplit, and KNOWN_SPLIT_SCHEMES from src/molhub/dataset/molecular.py; keep Frame.meta key constants and MolecularUnits
- [ ] Update regressions/mm-param-val-02-zinc-typing.py and regressions/mm-param-val-03-phalkethoh-mm.py to call .load()
- [ ] Add regression example regressions/python-native-dataset-protocol-05-mm.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

`FakeHub` 注入，无网络。zinc train `len == 3`，`Targets(frame)[MOLECULE_ID] == "m00"`，`atom_type == ["c3", "hc"]`。phalkethoh train `mm_energy` -1.0 / -1.5。包不再导出 `MolecularFrame` / `MoleculeSplit`。本 spec 回归脚本硬编码上述金值。旧 mm-param-val-02/03 改为 `.load()` 后金值不变。

## Out of scope

- 06 的公开 `resolve` / 用户文档
- `FrameCollection` 或任何新集合类型
- 改 Espaloma 科学内容或单位
- 让 `load()` 返回 `Trajectory`
- molnex `scripts/mm_param_learning/*` 调用方
- 把 02 `Dataset.fetch()` 推广到目录
- 改 `mm-param-val-01`（已经是集合形）
