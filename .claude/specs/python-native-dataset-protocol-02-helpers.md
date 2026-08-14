---
title: Python 原生数据集协议：资源助手
status: approved
created: 2026-08-12
revised: 2026-08-12
grilled: true
---

# Python 原生数据集协议：资源助手

## Summary

在 `python-native-dataset-protocol-01-types` 已落地的 `@dataset` 装饰类上，为数据集**实例**补齐只读清单与本地资源原语：`.manifest`（01 的 `DatasetManifest`）、`.cache_dir`、`.fetch(...)`、`.open(...)`。调用方可以在不实现 `load()`、不迁 QM9 的前提下，按坐标经注入的 `ArtifactHub` 取回完整本地文件，或在无坐标时按裸 `https://` / `file://` locator 走现有 `DownloadCache`；`open()` 只打开已经落在本地的文件得到二进制流。构造 `Cls()` 与读取 `.manifest` 不得触发 `hub.fetch`、不得联网。

## Design

本规格只扩展 `src/molhub/dataset/definition.py` 里 01 已经产出的装饰结果，不另起门面、不新增包层。**必须**新增资源基类 `DatasetHandle`（不要叫 `Dataset`——那个名字留给与 `torch.utils.data.Dataset` 对齐的协议）：拥有 `source`、`hub`、`cache_dir`、`fetch`、`open`。`@dataset` 若发现类尚未继承 `DatasetHandle`，则混入后仍返回**同一个类对象**。禁止再写 `fetch_dataset` / `open_dataset` 一类自由函数。

### 01 已存在、02 只消费的符号

- `@dataset`：装饰测试用类与未来入册类；本规格可用它写假类，不改装饰器的身份/编目语义。
- `DatasetManifest`：有 `@dataset` 时实例 `.manifest` 是 01 的清单，`coordinate` **必有**。分支条件是 `manifest is DatasetManifest` vs `manifest is None`，不要把 `DatasetManifest.coordinate` 改成可选。
- 无坐标 / 裸 locator 路径（CSV）**不走 `@dataset`**：未装饰的 `Dataset` 子类，`manifest is None`，才读 `source`（`DownloadCache` / `file://`）。04 的 `CSV` 是否继承本基类由 04 自定；本规格的无坐标测试用未装饰子类。
- 「入册」= 已应用 `@dataset`（有清单+坐标）。装饰器仍不写 01 的进程编目。

### 构造与所有权

```python
def __init__(self, *, hub: ArtifactHub | None = None) -> None: ...
```

- 仅关键字参数 `hub`。`Cls()` 必须继续合法。
- 注解是 `ArtifactHub | None`，**不是** `Molhub`。`definition.py` **模块顶层**不得 `import Molhub` / `from molhub.molhub import Molhub`（与 `hub.py` 同一条缝：下层按形状满足，替身不是子类问题）。
- `hub is None` 且真正执行 `fetch`/`open` 时，才在方法体内惰性 `from molhub.molhub import Molhub` 并调用 `Molhub().fetch(...)` —— 默认行为与现有 `QM9Dataset(..., hub=None)` 相同，但 Molhub 不进入 definition 的类型面。
- `hub` 存实例，不存类、不进进程内目录。
- 构造函数不得调用 `hub.fetch`，不得构造默认 `Molhub`，不得碰网络。`.manifest` 与 `.cache_dir` 同样如此：前者转发 01 清单，后者只算路径。

### 类属性 `source`

类型：`str | dict[str, str] | None`，缺省 `None`。只描述**无坐标**时的字节来源；有坐标时坐标优先。

| `source` | 有 `manifest.coordinate` | 无坐标 |
|---|---|---|
| `None` / 缺省 | `hub.fetch(coordinate, roles=...)`；role 由调用方给出，真实 `Molhub` 按 YAML registry artifacts 校验；本层不解析 YAML、不实现第二套 Source | 无物可取 → `ValueError` |
| 单个 locator 字符串（`https://…` / `http://…` / `file://…`） | **仍走 ArtifactHub**，忽略该字符串 | `https`/`http` → `DownloadCache.fetch`；`file://` → 本地 `Path`（不经 `HttpsSource`、不经 `DownloadCache`） |
| `dict[str, locator]` | **仍走 ArtifactHub**，`fetch("structures")` 把 role 传给 hub | `fetch("structures")` / `open("properties")` 按 key 取 locator，再走上一行规则 |

解析顺序写死为：**有 `DatasetManifest` 则走 ArtifactHub，否则读 `self.source`**。已装饰类若把 `source` 设成 locator 或 locator dict，装饰期 / `Dataset.__init_subclass__` 立刻 `ValueError`，消息同时含 `coordinate.canonical` 与该 locator —— 落实 product-02 ac-007，禁止静默忽略硬编码上游。未装饰的 `Dataset` 子类才允许裸 locator。`source` 用 `getattr(self, "source", None)`，实例可覆盖类属性。

`figshare://` / `zenodo://` / `hf://` 等 scheme **不是**本规格的 `source` 形态；无坐标时对它们 `ValueError`。那些 locator 只活在 registry YAML 里，由 `Molhub` → `Fetcher` → drivers 消化。本规格不碰 `Source` / `Drivers`。

### `fetch(role: str | None = None) -> Path`

返回**完整本地文件**的 `Path`，一次一个 role。

- 有坐标：`paths = hub.fetch(str(coordinate), roles=[role] if role else None)`。`role` 给定则返回 `paths[role]`（缺 role 时 `KeyError`，与 `ArtifactHub` 一致）。`role is None` 时若映射恰好一个 role，返回那一个 `Path`；多个则 `ValueError`，消息列出已知 role。
- 无坐标 + 字符串 `source`：忽略 `role`（传入非 `None` 且不是隐式单文件名则 `KeyError`）；按上一节取回一个文件。
- 无坐标 + dict `source`：`role` 必填（dict 仅一个 key 时可省略）；未知 key → `KeyError`。
- 返回前执行与 `BlobStore.has` / `DownloadCache.fetch` / `qm9._is_cached` 相同的谓词：`path.is_file() and path.stat().st_size > 0`。0 字节或缺失 → `FileNotFoundError`，即使假 `ArtifactHub` 交回了空文件。假 hub 的路径可以落在临时目录，不必已经在 `cache_dir` 里。
- **禁止**在本层重写传输（查 status / `.part` / 原子改名）。有坐标时字节与校验都是 `ArtifactHub`（默认即 `Molhub.fetch`）的职责。

### `open(role: str | None = None)`

`path = self.fetch(role); return path.open("rb")`。返回值是标准库二进制文件对象（context manager）。`open` **会**调用 `fetch`（因而可能下载）；「本地流」指返回的是 `Path` 上的文件句柄，不是 HTTP range / `urlopen`。

- 不是 HTTP range，不在 `HttpsSource` 上加流式，不 `urlopen`。
- `with ds.open(...) as fh: fh.read()` 的字节与 `ds.fetch(...).read_bytes()` 相同。

### `.cache_dir -> Path`

只读计算，不 `mkdir`、不取字节。

- 有坐标：`BlobStore().path_for(coordinate.cache_path())`，即 `$MOLHUB_HOME/files/<kind>/<ns>/<name>@<ver>`。必须用 `Coordinate.cache_path()`（`dataset/example/dummy@v1`），**禁止**把 `canonical`（含 `:`）丢进 `BlobStore` —— 那会塌成 `files/dataset_example/...`，与 TypeScript 共享布局以及 `Molhub.fetch` 使用的 `f"{cache_path()}/{role}"` 不一致。
- 无坐标 + 远程 URL：`DownloadCache().path_for(url).parent`（`$MOLHUB_HOME/urls/`，Python 本地，不是跨客户端契约）。
- 无坐标 + `file://`：该文件的父目录。

`cache_dir` 与假 hub 实际返回的临时文件可以不是同一棵树；回归只锁定布局键。

### 生命周期

1. 装饰类（可入册）—— 无 IO。入册 + locator `source` 在此失败。
2. `Cls()` / `Cls(hub=fake)` —— 只保存 `hub`，不 `fetch`。
3. `.manifest` / `.cache_dir` —— 纯数据 / 纯路径。
4. `.fetch` / `.open` —— 唯一取字节的入口。
5. 不要实现 `load()`。

测试假 hub 的形状照抄 `tests/test_dataset/test_qm9.py` 的 `FakeHub`（本模块自备，不抽共享假类型）：`fetch(coordinate, *, roles=None) -> dict[str, Path]`，并记录 `calls`。

### Reuse decision

- reuse `ArtifactHub` — `hub` 参数与 `fetch` 的坐标路径只调用该缝的 `fetch`；不扩展 `hub.py`。
- reuse `Molhub.fetch` — 仅经 hub 缝；默认在 `fetch`/`open` 时惰性构造 `Molhub()`，definition 模块顶层不绑定该类型。
- reuse `DownloadCache` — 无坐标的 `http(s)://` locator 调用已有 `DownloadCache.fetch`；0 字节重下契约沿用。
- reuse `BlobStore` / `Coordinate.cache_path` — `.cache_dir` 与角色文件键只由这两处组合，不手写第二套布局。
- new — `Source` + `Drivers`：本规格不解析平台 locator、不加流式；有坐标时那层已在 `Molhub.fetch` 内部。
- new — `MapDataset` / `IterableDataset` / `InMemoryDataset`：样本协议留给 03，本规格不实现 `load()`。
- new — `TargetSchema` / `Targets` / `MoleculeSplit`：不涉及样本语义。
- new — `Trajectory` / `FrameCollection`：不做。
- new — `TargetDeclaration`：不改 L2 manifest 契约。

## Files to create or modify

- `src/molhub/dataset/definition.py`（01 已创建；本规格扩展）
- `src/molhub/dataset/__init__.py`（导出 `Dataset`）
- `tests/test_dataset/test_definition.py`（01 已创建；本规格扩展；改写 01 的「`Dummy.__init__ is object.__init__` / definition.py 不得出现 ArtifactHub」分层断言）
- `regressions/python-native-dataset-protocol-02-helpers.py` (new)

## Tasks

- [ ] Write failing unit tests for Dataset resource helpers and `source` semantics (tests/test_dataset/test_definition.py → TestDataset, TestDatasetSource)
- [ ] Implement DatasetHandle plus cache_dir, fetch, open, and source resolution in src/molhub/dataset/definition.py; mix DatasetHandle into @dataset classes
- [ ] Export DatasetHandle from src/molhub/dataset/__init__.py
- [ ] Rewrite 01 layering asserts in tests/test_dataset/test_definition.py (Dummy.__init__ is Dataset.__init__; definition.py may import ArtifactHub/DownloadCache/BlobStore; still no module-level Molhub)
- [ ] Add Google-style docstrings for Dataset, source, cache_dir, fetch, and open in src/molhub/dataset/definition.py
- [ ] Add regression example regressions/python-native-dataset-protocol-02-helpers.py (public API only; hard-coded goldens, no third-party runtime)
- [ ] Verify dummy `@dataset` class: construct does not call hub, `fetch` via fake hub returns a temp file, `open` reads the same bytes, `cache_dir` matches `files/<kind>/<ns>/<name>@<ver>`
- [ ] Run full check + test suite

## Testing strategy

单测只放 `tests/test_dataset/test_definition.py`，类型镜像 `TestDataset` / `TestDatasetSource`；每条测试只打一个方法。用 01 的 `@dataset` 写假类，注入假 `ArtifactHub`，不访问真实网络、不 import QM9。

- **Happy path（`TestDataset`）**：`@dataset("dataset:example/dummy@v1")` 的实例 `.manifest.coordinate.canonical` 等于该字符串；`Cls(hub=fake)` 之后 `fake.calls == []`；读 `.manifest` 后仍为空；`fetch("main")` 调用 `fake.fetch("dataset:example/dummy@v1", roles=["main"])` 并返回假 hub 给出的 `Path`；`open("main")` 读出与该文件相同的字面量字节（建议 `b"molhub-dataset-helpers-v1"`）；`cache_dir` 在 `MOLHUB_HOME` 下精确等于 `files/dataset/example/dummy@v1`（`Coordinate.cache_path()` + `BlobStore.path_for`，不得出现 `dataset_example`）。
- **`source`（`TestDatasetSource`）**：无坐标 + `source="file:///…"` → `fetch()` 返回该本地文件且不调用 hub；无坐标 + `source="https://example.invalid/x.bin"` → 只委托 `DownloadCache.fetch`（monkeypatch 计数与 URL，不打真 HTTP）；无坐标 + `source={"structures": file_a, "properties": file_b}` → `fetch("structures")` / `open("properties")` 各回对应文件；有坐标时即使类上写了 URL，fetch 仍只打 hub（若装饰期已拒绝 URL，则装饰 `ValueError` 为主断言）。
- **入册硬编码 URL**：`@dataset("dataset:example/dummy@v1")` 且 `source="https://example.invalid/x.bin"` 必须 `ValueError`，消息同时含坐标与该 URL。
- **0 字节**：假 hub 返回空文件、或 `file://` 指向 0 字节路径时，`fetch`/`open` 抛 `FileNotFoundError`，不得把空文件当成命中。
- **缺 role / 无来源**：多 role 且省略 `role` → `ValueError`；未知 role → `KeyError`；无坐标且 `source is None` → `ValueError`。
- **分层**：`definition.py` 的模块级 import AST 不含 `Molhub`；`open` 路径上 monkeypatch `urllib.request.urlopen` 不得被调用。
- **回归**：`regressions/python-native-dataset-protocol-02-helpers.py` 只使用 `molhub.dataset` 公开 API。硬编码：坐标 `dataset:example/dummy@v1`、字节 `b"molhub-dataset-helpers-v1"`、相对缓存键 `files/dataset/example/dummy@v1`、构造后 `hub.calls == []`。不启动第三方、不访问网络。

## Out of scope

- `load()`、把装饰类接上 `MapDataset` / `IterableDataset` / `InMemoryDataset`（03）。
- 迁移 QM9 / revMD17 / 3BPA / CSV / Zinc / Phalkethoh 到新装饰器。
- 修改 `src/molhub/dataset/hub.py` 或给 `ArtifactHub` 增加 `open`。
- HTTP range、改 `HttpsSource`、在 L1 加流式。
- pydantic、`TargetDeclaration`、`TargetSchema` / `Targets` / `MoleculeSplit`。
- `Trajectory` / `FrameCollection`。
- 在 Python 类上解析 `figshare://` / `zenodo://` / `hf://`（那是 registry + `Molhub.fetch` 的事）。
- TypeScript / CLI / 改磁盘布局契约 / 自算 digest。
