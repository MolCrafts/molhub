---
title: Python-native dataset 取数入口（load 与 QM9 参考实现）
status: approved
created: 2026-08-12
revised: 2026-08-12
grilled: true
---

# Python-native dataset 取数入口（load 与 QM9 参考实现）

## Summary

调用方先构造数据集定义（`QM9(total=..., targets=...)`），再通过唯一取数入口 `load()` 得到可按下标访问的 Frame 集合；定义类不再扮演 `Dataset`。`load()` 返回 generalize 后的 `InMemoryDataset`（不是 `molpy.Trajectory`，也不引入 `FrameCollection`）。集合支持 `__iter__`、`__getitem__(int|slice)`（切片返回同类型集合而非 `list`）和 `materialize()`。QM9 用 01 已落地的 `@dataset(name="qm9", namespace="molcrafts", version="v2", ...)` 声明，只持坐标、不持 URL；`QM9()` 与 `import` 不下载，fetch 发生在 `load()` / `fetch()`。模块内 `QM9Dataset = QM9`，本阶段改写 `test_qm9`（以及联网样本数断言）走 `load()`，不把红灯留给 06。发现并一并处理：`tests/test_registry_data.py` 的联网用例仍对定义类做 `len(...)`；`TestIterableDatasetProtocol` 仍断言内存集合不可迭代——这两处随本规格改掉。README 旧用法留给 06。

## Design

本规格接在 01-types（`@dataset` / `DatasetManifest` / `Datasets`）与 02-helpers（`fetch` / `open` / `cache_dir`）之后，只改 L3 `molhub.dataset` 的集合协议与 QM9 参考实现。不新增 façade、不写 `make_*`、不把取数做成模块级函数，也不往 molpy 加类型层次。01 曾把内置迁移标成 04/05；本链把**第一条**参考实现定在 03，且**只迁 QM9**。

### 定义类与集合：两个对象，一个取数动词

定义类（装饰后的 `QM9`）拥有身份、视图参数和取字节能力。它**不是**样本序列：不实现 `__len__` / `__getitem__`，因而 `isinstance(QM9(...), Dataset)` 为假。

集合是 `load()` 的返回值。调用方组合为：构造定义 →（可选 `fetch()`）→ `load()` → 对集合下标 / 迭代 / 物化。`load()` 是定义类上的实例方法，本阶段只有 QM9 这一个实现（第二个调用点出现前不抽 `DatasetLoader` 协议）。

```python
from molhub.dataset import QM9, Targets

qm9 = QM9(total=100, targets=["U0", "gap"], hub=hub)
frames = qm9.load()          # InMemoryDataset
frame = frames[0]            # molpy.Frame
window = frames[:10]         # 仍是 InMemoryDataset
for sample in frames:
    Targets(sample).read()
ready = frames.materialize() # 已在内存则返回等价物
```

### 集合契约：generalize `MapDataset` / `InMemoryDataset`，并入 `IterableDataset`

01 已写明：集合行为留给 03，且不得把 `InMemoryDataset` 改名为 `FrameCollection`。本规格落实如下。

**文档契约（凡 `load()` 返回的集合必须满足）：**

- `__iter__` 产出 `Frame`
- `__getitem__(int)` 返回 `Frame`；越界 `IndexError`（负下标跟随底层序列）
- `__getitem__(slice)` 返回**同一具体类型**的集合，不是 `list`
- `materialize()` 返回内存集合 `InMemoryDataset`；调用方已在内存则返回等价物（允许返回 `self`）
- `source_id` 标识这一视图；切片是窗口，不新造 `#slice=` 限定符，继承父集合的 `source_id`

**运行时 `@runtime_checkable Dataset` 与 `torch.utils.data.Dataset` 所需面相同：`{__len__, __getitem__}`。`IterableDataset` 与 `torch.utils.data.IterableDataset` 相同：`{__iter__}`。** `source_id`、slice 保型、`materialize` 是 molhub **超集**，只挂在具体集合上，不写进 Protocol——否则一个纯 PyTorch 形对象过不了 `isinstance`。`TestDatasetProtocol` 必须包含一个只有 `__len__`/`__getitem__`、没有 `source_id` 的桩，它仍是 `Dataset`。

**`InMemoryDataset` 兑现集合契约：**

- `__iter__` 迭代内部 `list[Frame]`
- 切片返回新的 `InMemoryDataset`（同 `name`，同 `source_id`，帧为切片）
- `materialize()` 返回 `self`（已在内存）
- 构造增加可选 `source_id: str | None = None`；缺省仍为 `memory:{name}:{len}`

**`IterableDataset` 并入集合，不再当定义类协议。** 协议类型保留。`InMemoryDataset` 因此 **是** `IterableDataset`。定义类（`QM9`）两者都不是。

**`SubsetDataset` 仍 reuse 为 `MapDataset` 包装器。** 补齐 `__iter__`、切片（返回 `SubsetDataset`）和 `materialize()`。

禁止第三个消费 API 名字：不新增 `FrameCollection`、`MaterializedMap`、`FrameSeq` 等类型。

### QM9：定义类 + `load()` 参考实现

```python
@dataset(name="qm9", namespace="molcrafts", version="v2")
class QM9:
    ...

QM9Dataset = QM9
```

`QM9.manifest.canonical == "dataset:molcrafts/qm9@v2"`。类**只持坐标**，不持上游 URL。模块级 `COORDINATE` 若保留，必须等于 `QM9.manifest.canonical`。

`load()` 吸收今日的惰性 `_ensure_frames_loaded`：定义类删除 `_frames` 以及为了当 `MapDataset` 而存在的 `__len__` / `__getitem__`。返回 `InMemoryDataset(frames, source_id=self.source_id)`。不是 `molpy.Trajectory`。

### FrameCollection / Trajectory 评估（01 的边界，本阶段写进实现）

1. **独立分子不是轨迹。** QM9 每条样本是一个分子；多样本是样本集合。`molpy.Trajectory` 是同一 topology 上按 `step` / `time` 排列的时间序列。
2. **不在 molpy 引入 `FrameCollection`。** 通用「一组 Frame」是 molhub 的消费模型。本规格用已经公开的 `InMemoryDataset` 兑现。
3. **revMD17 多构象** 仍是按分子切开的样本集，不是 Trajectory；本阶段不迁它。

因此 `QM9.load()` 的返回值必须 `isinstance(..., InMemoryDataset)` 且 `not isinstance(..., Trajectory)`。

### 构造、视图参数、download 语义

```python
def __init__(
    self,
    root: str | Path | None = None,
    *,
    total: int | None = None,
    targets: list[str] | tuple[str, ...] | None = None,
    download: bool = True,
    hub: ArtifactHub | None = None,
) -> None: ...
```

- 视图参数 `total` / `targets` 留在 `__init__`。未知 target 仍在构造期 `ValueError`。
- `hub` 注入保留。
- `root` 改为可选，以便 `QM9()` 合法。
- `download=` 只影响 `load()`：`True` 时 `load()` 走 02 `fetch("main")` 与 `fetch("exclude")`；`False` 时 `load()` 只读 `root` 下既有文件且永不打 hub。不要让 02 的 `fetch()` 去读 `download=`。删除 classmethod `QM9.download`。
- `QM9()` 与 import 不下载。`FileNotFoundError` 改在 `load()` 抛，不在 `__init__`。
- `SubsetDataset` 切片与 `materialize()` **原样继承**父子集的 `source_id`（不要因切片重算 `:subset=` hash）。

### 保留的目标与 `source_id` 规则

- `ALL_TARGETS` / `TARGET_SCHEMA` 留在类上。
- 解析后继续 `Targets(frame).write(...)`。
- `source_id` 无限定时等于坐标；视图为 `#total=` / `#targets=`。

### Reuse decision

- generalize `Dataset`（原 `MapDataset`）— 运行时 Protocol 对齐 PyTorch：`__len__` + `__getitem__`；iter / slice / `materialize` / `source_id` 是超集
- generalize `IterableDataset` — 并入集合；`InMemoryDataset` 成为 `IterableDataset`
- generalize `InMemoryDataset` — 实现 iter、切片保型、`materialize()`、可选 `source_id=`
- reuse `SubsetDataset` — 仍包装 `MapDataset` 集合；补齐 iter / slice / `materialize`
- reuse `ArtifactHub` — `hub=` 注入与 FakeHub 测试缝不变
- reuse `Targets` — graph 目标仍 `write` / `read`
- reuse `TargetSchema` — `QM9.TARGET_SCHEMA` 保留
- reuse `Frame` / `Element` / `Block` — `_parse_xyz` 的样本模型不变
- reuse `dataset` / `DatasetManifest` / `Datasets` — 01 的声明面
- reuse `Coordinate` / `InvalidCoordinate` — 身份与 `source_id` 无限定形
- reuse 02 `fetch` / `open` / `cache_dir` — `load()` 取字节
- generalize `QM9Dataset` — 改形为定义类 `QM9`；`QM9Dataset = QM9`
- reuse `TargetDeclaration` — 不在 L3 复制 YAML targets
- new — 不使用 `molpy.Trajectory`（独立分子不是轨迹）
- new — 不引入 `FrameCollection`（消费面沿用 `InMemoryDataset`）
- unused `MoleculeSplit` — 05
- unused `DownloadCache` — QM9 有坐标
- unused `Drivers` — 不进入 L3 `load()` 路径

## Files to create or modify

- `src/molhub/dataset/protocol.py`
- `src/molhub/dataset/qm9.py`
- `src/molhub/dataset/__init__.py`
- `tests/test_dataset/test_protocol.py`
- `tests/test_dataset/test_qm9.py`
- `tests/test_registry_data.py`
- `regressions/python-native-dataset-protocol-03-load.py` (new)

## Tasks

- [ ] Write failing unit tests for InMemoryDataset iter/slice/materialize and IterableDataset-as-collection (tests/test_dataset/test_protocol.py → TestInMemoryDataset, TestIterableDatasetProtocol, TestSubsetDataset)
- [ ] Generalize InMemoryDataset and complete SubsetDataset in src/molhub/dataset/protocol.py for __iter__, __getitem__(int|slice) returning the same concrete type, materialize(), and optional source_id=; slice/materialize inherit source_id
- [ ] Document the load() collection contract on Dataset/IterableDataset; required Protocol members match torch.utils.data; TestDatasetProtocol includes a __len__/__getitem__ stub with no source_id that is still Dataset
- [ ] Write failing unit tests for QM9.load() and definition-is-not-collection (tests/test_dataset/test_qm9.py → TestQM9); point the network sample-count assertion in tests/test_registry_data.py at load()
- [ ] Generalize QM9Dataset in src/molhub/dataset/qm9.py to a @dataset definition class QM9 whose load() returns InMemoryDataset (absorb _ensure_frames_loaded; QM9Dataset = QM9; delete QM9.download)
- [ ] Export QM9 from src/molhub/dataset/__init__.py while keeping QM9Dataset
- [ ] Add docstring per google with units on QM9.load, InMemoryDataset.__getitem__, and InMemoryDataset.materialize in src/molhub/dataset/qm9.py and src/molhub/dataset/protocol.py
- [ ] Add regression example regressions/python-native-dataset-protocol-03-load.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Verify QM9.load() against the miniature fixture tarball (atom count and target keys)
- [ ] Run full check + test suite

## Testing strategy

单测只放在镜像路径：`tests/test_dataset/test_protocol.py`、`tests/test_dataset/test_qm9.py`。每个测试只打一个方法。禁止真实网络。

- **Happy path（集合）：** 两个 `Frame` 的 `InMemoryDataset`：`list(iter(ds))` 长度 2；`ds[0]` 为 `Frame`；`ds[:1]` 是 `InMemoryDataset`（不是 `list`）；`ds.materialize() is ds`；同时是 `MapDataset` 与 `IterableDataset`。
- **Edge（集合）：** 空集合、空切片、负下标、`source_id=` 覆盖、`SubsetDataset` 切片与 `materialize`。
- **Happy path（QM9）：** 微型 tarball；`load()` 得到 `InMemoryDataset`；`Targets` 读 graph keys；`QM9Dataset is QM9`；定义类不是 `MapDataset`；不是 `Trajectory`。
- **Edge（QM9）：** 排除表、`total` 抽样、未知 target 在 `__init__` 失败、缺文件在 `load()` 失败、构造不 fetch。
- **联网金标：** `tests/test_registry_data.py` 改为 `len(QM9(...).load()) == 130831`。
- **Regression：** `regressions/python-native-dataset-protocol-03-load.py`，FakeHub + 微型 tarball，硬编码长度 / 原子数 / 15 个 graph key。

## Out of scope

- 其他内置定义类迁 `load()`（04/05）
- 收紧 `MapDataset` 运行时 Protocol 以致未迁类的 `isinstance` 变红
- 包级 `molhub.dataset.resolve`、README（06）
- 在 molpy 引入 `FrameCollection`，或让 `QM9.load()` 返回 `Trajectory`
- Molhub 上的 stream / preview API
- 改 `MoleculeSplit`（05）
- 改 YAML schema
