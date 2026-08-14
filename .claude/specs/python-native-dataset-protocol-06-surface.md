---
title: 整理 Python dataset 公开面（定义 + load()）
status: approved
created: 2026-08-12
revised: 2026-08-12
grilled: true
---

# 整理 Python dataset 公开面（定义 + load()）

## Summary

整理 `molhub.dataset` 的公开进口与文档，使规范用法成立：`from molhub.dataset import QM9` 得到定义类，`QM9().load()` 才物化集合；`resolve("dataset:molcrafts/qm9@v2")` 与 `resolve("molcrafts/qm9@v2")` 返回同一个类，且与 `QM9` 是同一对象；`import molhub` 与导入定义都不触发下载。`*Dataset` 别名保留。L1/L2 的 coordinate / manifest / fetch / cache 合同不变；`Molhub.resolve` 仍返回 `Manifest`。本变更是单一公开 Python 面（barrel + 发布该 barrel 的文档），不是跨层拆分。

## Design

01–05 已落地：内置数据集是带 `@dataset` 的**定义类**，物化入口是 `load()`。本 spec 整理公开面，并**实现**包级 `molhub.dataset.resolve`（01 明确没有进程缺省编目与包级 resolve）。

### 公开进口（barrel）

`src/molhub/dataset/__init__.py` 必须可写：

```python
from molhub.dataset import (
    QM9, RevMD17, ThreeBPA, ZincTyping, PhalkethohMM, CSV,
    dataset, DatasetManifest, resolve,
)
```

规范短名与历史名是**同一个对象**。既有导出继续留在 `__all__`。`CSV` 仍是本地/裸 URL 加载器，不是 registry 定义，`resolve` 不命中它。

**不要**改 `src/molhub/__init__.py`。

### 包级 `resolve`（本规格实现）

01 的 `Datasets` 是显式、不可变编目，装饰器不写全局表。06 提供：

```python
def resolve(coordinate: str | Coordinate) -> type:
    return builtin_datasets().resolve(coordinate)
```

实现为 `Datasets.of(QM9, RevMD17, ThreeBPA, ZincTyping, PhalkethohMM).resolve(coordinate)`（或同一编目藏在**私有** helper 后）。`builtin_datasets` **不是公开符号**——不进 `__all__`，不做 `Datasets.builtin`，不设模块级可变注册表。`kind` 缺省 `dataset`：`resolve("molcrafts/qm9@v2")` 经 `Coordinate.coerce` / `parse` 扩成全称。未知坐标抛 `UnknownDataset`。`resolve` 返回类对象，不是实例，也不是 L2 `Manifest`。它与 `Molhub.resolve` 是不同符号。CSV 不进默认编目。

### 生命周期

- `import molhub` 不得 import `molhub.dataset`。
- `from molhub.dataset import QM9` 不得调用 `ArtifactHub.fetch`。
- 物化只发生在 `load()`。
- `MapDataset` 是 `load()` 返回值上的集合协议。

### 文档合同（定点）

1. `README.md`：主示例改为 `QM9().load()`。
2. `CLAUDE.md` 只改「`molhub.dataset` 的公开协议」那一句。
3. `molhub-product-02` 只改 `## Python dataset layer`；`status: implemented` 保持；Transport / Cache / Conformance 不动。
4. `docs/reference/python.md` 补 dataset 符号；不要加会触发下载的可执行 fence。

### Reuse decision

- reuse `dataset` / `DatasetManifest` / `Datasets` / `UnknownDataset` — 01
- reuse `Coordinate.parse` / `coerce` — kind 缺省
- reuse 各 `*Dataset` 短名别名 — 03–05
- reuse `MapDataset` / `IterableDataset` — 集合协议挂在 `load()` 返回值
- reuse `ArtifactHub` — import 不得调用
- new `molhub.dataset.resolve` — 包级薄封装，不是第二套坐标解析

## Files to create or modify

- `src/molhub/dataset/__init__.py`
- `README.md`
- `CLAUDE.md`
- `docs/reference/python.md`
- `.claude/specs/molhub-product-02-clients-transport.md`
- `tests/test_dataset/test_resolve.py` (new)
- `regressions/python-native-dataset-protocol-06-surface.py` (new)

## Tasks

- [ ] Write failing unit tests for public surface (tests/test_dataset/test_resolve.py → TestPublicSurface, TestResolve, TestImportCheapness)
- [ ] Implement package-level resolve wrapping Datasets.of(built-ins) and export QM9, RevMD17, ThreeBPA, ZincTyping, PhalkethohMM, CSV, *Dataset aliases, dataset, DatasetManifest, and resolve from src/molhub/dataset/__init__.py
- [ ] Revise README.md dataset intro, capabilities rows, and examples to QM9().load(); mention MapDataset only as the collection protocol on the load() return
- [ ] Update the CLAUDE.md 「molhub.dataset 的公开协议」 sentence to decorator + load() + collection-on-return (MapDataset is the collection protocol)
- [ ] Revise only the 「Python dataset layer」 paragraph in .claude/specs/molhub-product-02-clients-transport.md; keep status implemented; leave transport/cache/conformance untouched
- [ ] Add dataset symbols to docs/reference/python.md (mkdocstrings `:::`; no download-triggering fences)
- [ ] Add regression example regressions/python-native-dataset-protocol-06-surface.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Run full check + test suite

## Testing strategy

`tests/test_dataset/test_resolve.py`：短名 `is` 别名；`resolve` 全称与缺省 kind 都返回 `QM9`；import 不调用 `Molhub.fetch`。回归脚本禁止建 socket，不调用 `load()`。

## Out of scope

- 再实现一套坐标解析
- 改 YAML schema
- 引入 `FrameCollection`
- 改 L1 传输 / 缓存 / conformance
- 把 dataset 再导出到 `molhub` 根包
- 把 product-02 整份标回 `approved`
