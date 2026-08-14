---
title: 将 RevMD17 / ThreeBPA / CSV 迁到 @dataset + load()
status: approved
created: 2026-08-12
grilled: true
---

# 将 RevMD17 / ThreeBPA / CSV 迁到 @dataset + load()

## Summary

把 `RevMD17`、`ThreeBPA`、`CSV` 收成与 03 落地后的 QM9 同一交互：定义类只持身份与视图参数，import / 构造不碰网络也不读字节；`fetch()` 取本地路径，`load()` 解析后返回 03 推广过的 `InMemoryDataset`。坐标制品只通过注入的 `ArtifactHub` 按现有 `COORDINATE` 取单一 role；CSV 覆盖无 registry 的 URL / 本地路径，仍走 `DownloadCache`，不假装自己是坐标制品。模块内保留 `*Dataset` 别名；`source_id`、`TARGET_SCHEMA`、`Targets` 的既有形式不变。

## Design

本规格只改三个 L3 读取器及其镜像测试，不改 `protocol.py`、`definition.py`、YAML registry，也不给 Zinc / Phalkethoh 做同一迁移。

### 交互模型（对齐 03 的 QM9）

定义类**不是** `MapDataset`：去掉 `__len__` / `__getitem__`。调用方写 `RevMD17(molecule="aspirin", hub=hub).load()`，对返回的集合做 `len` / `[i]` / `[:1]`。

每个定义类暴露与 QM9-after-03 相同的两个原语（若 02 已抽出共享 mixin / helper，三个模块调用它，不平行写第二套传输编排）：

- `fetch(self) -> Path` — 只取字节，落到一个本地文件，不解析。
- `load(self) -> InMemoryDataset` — 调用 `fetch()`，解析为 `list[Frame]`，再交给 03 推广后的 `InMemoryDataset(..., source_id=...)`。

默认 hub / cache 只在 `fetch()` 里惰性构造。构造器只保存注入缝与视图参数。

### 短名、别名、装饰器身份

| 短名 | 模块 | 装饰器身份 | 模块级常量 | 别名 |
|---|---|---|---|---|
| `RevMD17` | `revmd17.py` | `@dataset(name="revmd17", namespace="molcrafts", version="v4")` | `COORDINATE = "dataset:molcrafts/revmd17@v4"` | `RevMD17Dataset = RevMD17` |
| `ThreeBPA` | `threebpa.py` | `@dataset(name="3bpa", namespace="molcrafts", version="v1")` | `COORDINATE = "dataset:molcrafts/3bpa@v1"` | `ThreeBPADataset = ThreeBPA` |
| `CSV` | `csv_dataset.py` | **不**使用 `@dataset` | 无 `COORDINATE` | `CSVDataset = CSV` |

`CSV` 不是坐标制品：给它挂 `DatasetManifest` 会造出带 `@` 的假坐标。它只共享构造 / `fetch` / `load` 交互，不进入 01 的类编目。裸 URL / 本地路径走 02 的 `source` 解析（`DownloadCache` / `file://`），不要求 01 允许「无坐标的 `@dataset`」。

`@dataset` 按 01：只写 `Cls.manifest`，不包装 `__init__`，不在装饰时 IO。禁止再引入 `BASE_URL` 或任何上游 URL 常量。

### 视图参数留在构造器

```python
RevMD17(molecule: str = "aspirin", *, hub: ArtifactHub | None = None)
ThreeBPA(*, tag: str, hub: ArtifactHub | None = None)
CSV(path_or_url: str, *, cache: DownloadCache | None = None)
```

- `RevMD17`：去掉 `root` / `download`。未知 `molecule` 在构造期 `ValueError`。合法分子名即 manifest role；`fetch()` 只请求 `roles=[molecule]`。
- `ThreeBPA`：去掉第一位置参数 `path` 以及「本地文件存在则跳过 hub」的双通道。`tag` 必须是 `SPLITS` 之一。`fetch()` 只请求 `roles=[tag]`。
- `CSV`：`path_or_url` 是唯一视图。`http(s)://` → `DownloadCache.fetch`（落在 `$MOLHUB_HOME/urls/`）。其它字符串当本地路径。不调用 `ArtifactHub`。删除类方法 `CSV.download` 与构造器 `download=`。

### 为何返回 InMemoryDataset，而不是 Trajectory

现有解析面**没有**时间轴：revMD17 NPZ 没有 `step`/`time`；3BPA extxyz 不读时间戳。01 已写明 `Trajectory` 只表示同一 topology 上按时间排列的帧。`load()` **必须**返回 03 的 `InMemoryDataset`。

`source_id`：

- `dataset:molcrafts/revmd17@v4#molecule=<molecule>`
- `dataset:molcrafts/3bpa@v1#split=<tag>`
- `csv:<filename>:n=<nrows>`（`@` 不得出现）

### Reuse decision

- reuse `dataset`（01）— `RevMD17` / `ThreeBPA` 的身份只经装饰器
- reuse `ArtifactHub` — 两个坐标制品的唯一取字节缝
- reuse `DownloadCache` — CSV 远程 URL 的唯一取字节缝
- reuse `Targets` / `TargetSchema` — 能量与列布局
- reuse `InMemoryDataset`（03）— `load()` 的唯一返回类型
- unused `molpy.Trajectory` — 解析结果无 `step` / `time`
- unused `MoleculeSplit` / 包级 `resolve` — 05/06

## Files to create or modify

- `src/molhub/dataset/revmd17.py`
- `src/molhub/dataset/threebpa.py`
- `src/molhub/dataset/csv_dataset.py`
- `src/molhub/dataset/__init__.py`
- `tests/test_dataset/test_revmd17.py`
- `tests/test_dataset/test_threebpa.py`
- `tests/test_dataset/test_csv_dataset.py`
- `regressions/python-native-dataset-protocol-04-migrate.py` (new)

## Tasks

- [ ] Write failing unit tests for RevMD17, ThreeBPA, and CSV (tests/test_dataset/test_revmd17.py → TestRevMD17; tests/test_dataset/test_threebpa.py → TestThreeBPA; tests/test_dataset/test_csv_dataset.py → TestCSV)
- [ ] Implement RevMD17 and RevMD17Dataset alias in src/molhub/dataset/revmd17.py
- [ ] Implement ThreeBPA and ThreeBPADataset alias in src/molhub/dataset/threebpa.py
- [ ] Implement CSV and CSVDataset alias in src/molhub/dataset/csv_dataset.py
- [ ] Export RevMD17, ThreeBPA, CSV and their *Dataset aliases from src/molhub/dataset/__init__.py
- [ ] Add Google-style docstrings with units on RevMD17, ThreeBPA, CSV, fetch, and load
- [ ] Add regression example regressions/python-native-dataset-protocol-04-migrate.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Verify fixture facts: aspirin NPZ 3 frames / energy -10.0; 3BPA extxyz 2 frames / energy -40.50; CSV 5 rows / Tg 345.15
- [ ] Run full check + test suite

## Testing strategy

坐标制品只用模块内 `FakeHub`。CSV 远程只用注入的 `DownloadCache` + fake `FileTransfer`。回归脚本内嵌微型夹具，硬编码 `len` / `source_id` / 能量 / Tg。

## Out of scope

- Zinc / Phalkethoh（05）
- MoleculeSplit、包级 resolve、README（06）
- FrameCollection / Trajectory
- 改 YAML schema
- 保留 `root` / `path` / `download=` 旧构造
