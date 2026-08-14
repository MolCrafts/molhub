---
title: Python-native dataset 声明面（类型与编目）
status: approved
created: 2026-08-12
grilled: true
---

# Python-native dataset 声明面（类型与编目）

## Summary

本规格只落地 Python-native dataset 的声明面：用小写装饰器 `@dataset(...)` 给类绑定一份与 loader 解耦的冻结 `DatasetManifest`，身份复用现有 `Coordinate`（`kind` 固定为 `dataset`，canonical 为 `dataset:namespace/name@version`），并用仿 `Drivers` 的不可变编目类型 `Datasets` 提供 `resolve(coordinate) -> type`。装饰后的类构造 `Cls()` 不触发任何 IO；本阶段没有 `load()` / `fetch()` / `open()`，也不改 QM9 等内置实现。调用方可把清单 `asdict` / JSON 独立序列化，并在显式构造的编目上按坐标找回类。包级 `molhub.dataset.resolve` 留给后续 06。

## Design

本规格只新增 L3 声明类型，不引入 façade、不引入 `make_*` / `register_dataset`，也不把编目藏进模块级可变 `dict`。集合协议仍留在 `protocol.py`；本规格不往 molpy 加类型层次。

### 身份：复用 `Coordinate`，不另造语法

装饰器关键字参数至少为 `name`、`namespace`、`version`；可选 `description`、`license`、`homepage`、`citation`、`tags`。不接受 `kind`——清单身份一律：

```python
Coordinate(kind="dataset", namespace=namespace, name=name, version=version)
```

字符规则、报错类型与文案全部交给 `Coordinate.__post_init__`（`InvalidCoordinate`）。禁止在 `definition.py` 重写 `_SEGMENT` / `_VERSION` 或手写另一套校验。不走 `Coordinate.parse` 拼字符串，以免误触发 `qm9@v2` → `dataset:molcrafts/qm9@v2` 的缺省展开；三段都由调用方显式给出。

canonical 恒为 `dataset:<namespace>/<name>@<version>`，例如 `dataset:molcrafts/dummy@1.0`。

### `DatasetManifest`：冻结值对象，与 loader 解耦

`DatasetManifest` 是 `@dataclass(frozen=True)`，不是 pydantic model，也不实现取数。字段：

- `coordinate: Coordinate` — 唯一身份；不把 `name` / `namespace` / `version` 再存一份，以免漂移
- `description: str = ""`
- `license: str | None = None`
- `homepage: str | None = None`
- `citation: str | None = None`
- `tags: tuple[str, ...] = ()` — 调用方传入的 `list` 在构造时收成 `tuple`

只读属性 `canonical` 转发给 `coordinate.canonical`（属性不进 `asdict`）。序列化形状就是 stdlib `dataclasses.asdict` 的嵌套结果：`coordinate` 展开为 `{kind, namespace, name, version}` 四个字符串；`json.dumps(asdict(manifest))` 必须直接成功，不写自定义 encoder，也不在 `definition.py` 里 import `json`。

`DatasetManifest` **不**承载 target 布局。L3 布局继续只用已有 `TargetSchema`（类属性 `TARGET_SCHEMA` 的既有惯例）；L2 `TargetDeclaration` 属于 YAML registry manifest，本规格不抄一份进 Python 声明面。装饰器参数表因此没有 `targets`。

### `@dataset(...)`：附着清单，不包装构造，不写全局表

导出名必须是 `dataset`（小写）。它是模块级装饰器函数——用户点名要求的声明句法，不是 `register_dataset` / `make_*` 工厂，也不是隐藏的全局注册表入口。

装饰时：用上面的 `Coordinate(...)` 建身份 → 建 `DatasetManifest` → 写成 **类属性** `Cls.manifest` → **原样返回同一个类**。不包装 `__init__`、不注入 `ArtifactHub` / `Molhub`、不在装饰时打开文件或访问网络。因此空类

```python
@dataset(name="dummy", namespace="molcrafts", version="1.0")
class Dummy:
    pass
```

上的 `Dummy()` 不得触发任何 IO；`Dummy.manifest` 是 `DatasetManifest`，`Dummy.manifest.canonical == "dataset:molcrafts/dummy@1.0"`。

本阶段允许（也只需要）测试/回归里的空类验证装饰器。禁止改 `QM9Dataset` 等内置实现的 `COORDINATE` 字段——那是 04/05 的迁移。

### `Datasets`：进程内编目类型，不是模块级 dict

编目类型命名为 `Datasets`，对齐 `Drivers`（按所容纳对象命名），避免占用 notes 里留给 YAML 的 `Registry`，也避免和 Web Catalog 抢 `Catalog`。

形状仿 `src/molhub/sources/drivers/__init__.py` 的 `Drivers`：

- `Datasets()` / `Datasets.of(*classes)` 从已装饰（或至少带有 `DatasetManifest` 类属性）的类构造
- `with_dataset(cls) -> Datasets` 返回**新**集合；接收者不变
- 同一 canonical **后写覆盖**（后插入的类赢），与 `Drivers.with_driver` 对同 scheme 的策略一致
- 内部用 dict 按 `coordinate.canonical` 索引，但不把该 dict 暴露为模块级 `_DATASETS = {}`，也不在装饰器里替换某个进程单例

查找对齐 `Registry.get` 的坐标习惯，而不是 `Drivers.for_scheme` 的 scheme 小写：

- `resolve(coordinate: str | Coordinate) -> type`：先 `Coordinate.coerce`
- `kind != "dataset"` → `InvalidCoordinate`（本编目只收 dataset）
- 未命中 → `UnknownDataset`（`KeyError` 子类，仿 `UnknownArtifact`）；消息列出已有 canonical，仿 `UnknownScheme` 列出 scheme
- 可选 `coordinates() -> tuple[Coordinate, ...]`，插入序，对标 `Drivers.schemes()`

本阶段 **没有** 进程隐式编目，也 **没有** 包级 `molhub.dataset.resolve`。要解析，调用方必须拿着自己的 `Datasets` 实例（测试里即 `Datasets.of(Dummy)`）。装饰器不登记、不发现、不读 entry point。包级 `resolve` 与进程缺省编目留给 06。

`UnknownDataset` 与上述三个公开符号一并从 `molhub.dataset` 导出，供调用方捕获。

### 生命周期与所有权

- `DatasetManifest` 冻结，生命周期等于持有它的类属性
- `Datasets` 拥有「canonical → 类」映射；每次 `with_dataset` 换新实例
- 类实例的生命周期仍由该类自己的 `__init__` 决定；声明面不拥有字节、路径或 Frame
- `definition.py` 只依赖 `molhub.coordinate`（`Coordinate` / `InvalidCoordinate`）。禁止 import `molhub.molhub`、`molhub.sources`、`molhub.dataset.hub`、`molhub.dataset.cache`、`molhub.registry`、`pydantic`

### FrameCollection 评估

用户点名要求在本规格写清，且本阶段 **零代码** 落实下列边界：

1. **不在 molpy 引入 `FrameCollection` 类层次。** 通用「一组 Frame」不是 molpy 的领域概念；把它做成基类会把 molhub 的数据集模型倒灌进 molpy，并迫使独立分子、轨迹、流式源共享一个错误的 isa 关系。
2. **`molpy.Trajectory` 只表示同一体系的时间序列**（同一 topology 上按 `step` / `time` 排列的帧）。它不是通用数据集容器。QM9 这类「许多独立分子」不是 Trajectory；把它们塞进 Trajectory 等于谎称共享拓扑与时间轴。
3. **独立分子 ≠ Trajectory。** 一条样本是一帧分子；多样本是样本集合，不是一条轨迹。revMD17 单个分子的多构象也只是按分子切开的样本集，在声明面仍不是 Trajectory。
4. **集合行为（iter / slice / materialize）留给 03。** 现有 `MapDataset` / `IterableDataset` / `InMemoryDataset` 已经是公开协议与内存实现；03 将 generalize 它们以覆盖声明式数据集的集合语义。本规格不新增 `__len__` / `__getitem__` / `__iter__`，不把 `InMemoryDataset` 改成 FrameCollection，也不让 `DatasetManifest` 描述长度或切片。

因此本规格的公开对象只有「身份 + 书目元数据 + 类编目」，没有「一组 Frame」。

### 放置

新代码放在 `src/molhub/dataset/definition.py`，让 `protocol.py` 继续只承担集合协议与 `InMemoryDataset` / `SubsetDataset`。`molhub.dataset.__init__` 增加导出，不改顶层 `molhub.__init__`。

### Reuse decision

- reuse `Coordinate` / `InvalidCoordinate` — 装饰器与 `resolve` 的身份、字符规则、`coerce` 全部走现有类型
- reuse `TargetSchema` — 装饰器不重做 target 布局；类继续用已有 `TARGET_SCHEMA`，`DatasetManifest` 不长平行字段
- reuse `TargetDeclaration` — 不把 L2 YAML `targets` 抄进 Python 声明面；书目清单与 registry manifest 保持两种值对象
- reuse `molpy.Trajectory` — 仅作 Design 语义边界（同一体系时间序列），本规格不 import、不子类化
- pattern `Source` + `Drivers` — `Datasets.of` / `with_dataset` / 后写覆盖 / 不可变集合照此读
- pattern `QM9Dataset` 及其他 `*Dataset` — 现有模块级 `COORDINATE` 字符串是将被装饰器身份取代的旧模式；本阶段只对照、不改这些类
- defer generalize `MapDataset` — 集合协议的 generalize 在 03，本规格不改 `protocol.py`
- defer generalize `IterableDataset` — 同上，留给 03
- defer generalize `InMemoryDataset` — materialize / 内存集合留给 03
- unused `SubsetDataset` — 本规格不做视图
- unused `ArtifactHub` — 无 fetch
- unused `Molhub.fetch` — 无传输
- unused `Targets` — 不写 `Frame.meta`
- unused `MolecularFrame` — 无样本对象
- unused `MoleculeSplit` — 无划分
- unused `BaseTrajectoryReader` — 无轨迹 IO
- unused `molpy.Frame` — 声明面不持有样本
- new `dataset` / `DatasetManifest` / `Datasets` / `UnknownDataset` — 现有符号里没有「Python 类的冻结书目清单 + 不可变类编目」；`Manifest` 是 YAML 字节清单，`Registry` 是文件目录，都不能表达可执行类

## Files to create or modify

- `src/molhub/dataset/definition.py` (new)
- `src/molhub/dataset/__init__.py`
- `tests/test_dataset/test_definition.py` (new)
- `regressions/python-native-dataset-protocol-01-types.py` (new)

## Tasks

- [ ] Write failing unit tests for DatasetManifest (tests/test_dataset/test_definition.py → TestDatasetManifest)
- [ ] Write failing unit tests for dataset and Datasets (tests/test_dataset/test_definition.py → TestDataset, TestDatasets)
- [ ] Implement DatasetManifest, UnknownDataset, dataset, and Datasets in src/molhub/dataset/definition.py
- [ ] Export dataset, DatasetManifest, Datasets, and UnknownDataset from src/molhub/dataset/__init__.py
- [ ] Add Google-style docstrings for dataset, DatasetManifest, Datasets, and UnknownDataset in src/molhub/dataset/definition.py
- [ ] Add regression example regressions/python-native-dataset-protocol-01-types.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Verify TestDatasetManifest, TestDataset, TestDatasets and regressions/python-native-dataset-protocol-01-types.py against dataset:molcrafts/dummy@1.0
- [ ] Run full check + test suite

## Testing strategy

单测只放在 `tests/test_dataset/test_definition.py`，类型镜像：`DatasetManifest` → `TestDatasetManifest`，`dataset` → `TestDataset`，`Datasets` → `TestDatasets`。每个测试只打一个方法/行为；禁止在 `tests/` 里做跨模块 e2e，禁止 import `QM9Dataset` / `Molhub` / 真实 hub。

- **Happy path：** `@dataset(name="dummy", namespace="molcrafts", version="1.0")` 装饰空类 `Dummy` 后，`Dummy.manifest` 是冻结 `DatasetManifest`；`Dummy.manifest.canonical == "dataset:molcrafts/dummy@1.0"`；`Dummy.manifest.coordinate` 等于 `Coordinate(kind="dataset", namespace="molcrafts", name="dummy", version="1.0")`；`dataclasses.asdict(Dummy.manifest)["coordinate"]` 为 `{"kind": "dataset", "namespace": "molcrafts", "name": "dummy", "version": "1.0"}`；`json.dumps(asdict(...))` 成功；`Datasets.of(Dummy).resolve("dataset:molcrafts/dummy@1.0") is Dummy`；`resolve` 也接受该 `Coordinate` 实例与 shorthand `"dummy@1.0"`（`Coordinate.coerce` 展开到同一 canonical）。
- **Edge cases：** `name` 为 `QM9` / `qm 9` / `-qm9` / `qm.9` / `qm_9`、`namespace` 为 `MolCrafts`、`version` 为 `!bad` 时装饰器抛 `InvalidCoordinate`（与 `tests/test_coordinate.py` 同一字符规则）；`resolve("model:molcrafts/mace-mp-0@1.0")` 抛 `InvalidCoordinate`；空编目或未知坐标抛 `UnknownDataset` 且消息含已有 canonical；`with_dataset` 返回新实例且后写覆盖同一 canonical；原 `Datasets` 不因 `with_dataset` 获得新条目；`tags=["a"]` 存成 `("a",)`；`Dummy()` 成功且 `Dummy.__init__` 仍是未包装的 `object.__init__`（或子类自己的 `__init__`，而非装饰器注入的 fetch 包装）。
- **分层守护：** 读 `definition.py` 源文本，断言不出现 `pydantic`、`ArtifactHub`、`Molhub`、`molhub.sources`、`molhub.registry`，且模块作用域没有可变 `dict` 注册表。
- **Regression example：** `regressions/python-native-dataset-protocol-01-types.py`。脚本只用 `molhub.dataset` 公开 API 装饰空类 `Dummy`，硬编码断言 `Dummy.manifest.canonical == "dataset:molcrafts/dummy@1.0"`、`asdict` 的 `coordinate` 四段字面量、`json.dumps` 成功、`Datasets.of(Dummy).resolve("dataset:molcrafts/dummy@1.0") is Dummy`、`Dummy()` 成功。黄金值写在脚本字面量里（注释：tool `python`，command `uv run python regressions/python-native-dataset-protocol-01-types.py`，date 2026-08-12）；运行时不 import、不 subprocess 任何第三方 oracle。

## Out of scope

- `fetch` / `open` / `load` 以及装饰类构造时的任何 IO
- 迁移 `QM9Dataset` / `RevMD17Dataset` / `ThreeBPADataset` / `CSVDataset` / `ZincTypingDataset` / `PhalkethohMMDataset`（04/05）
- 包级 `molhub.dataset.resolve` 与进程缺省编目（06）
- generalize `MapDataset` / `IterableDataset` / `InMemoryDataset` 的 iter/slice/materialize（03）
- pydantic model、自定义 JSON encoder
- 改 `spec/manifest.schema.yaml`、bundled YAML registry、L2 `Manifest` / `Registry`
- 在 molpy 引入 `FrameCollection`，或把 `Trajectory` 当成通用数据集
- HTTP range、entry-point 发现、`Datasets.builtin` / `discover`
- 改顶层 `molhub.__init__` 或 `protocol.py`
