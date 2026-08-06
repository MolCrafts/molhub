---
slug: registry-core-01-transport
status: in-progress
created: 2026-08-06
chain: registry-core
position: 1
depends_on: []
scope_layer: L1 transport
---

# registry-core-01-transport — 可继承的 Registry 驱动 + digest 强校验取回

## Summary

建立 molhub 的 L1 传输层 `molhub.registry`：一套**可继承的 `Registry` 驱动接口**，
每个远端托管平台实现一次；一个**按序 fallback + digest 强校验**的取回器；一个
**内容寻址的本地缓存**。本层只认字节，完全不认分子——不解析、不构造 `Frame`、
不认识坐标。

这是整条链唯一完全落在本仓、且不依赖任何外部仓库就能验收的一块。

## Domain basis

本层无物理内容（`mol_project.science.required: false`）。约束来自上游平台的真实行为：

- **Zenodo** REST `/api/records/<id>` 返回 `files[].checksum`（形如 `md5:ce2c…`）、
  `files[].size`、`conceptdoi` 与版本 DOI。发布后文件不可变。
- **Figshare** REST `/v2/articles/<id>/files` 返回 `supplied_md5` / `computed_md5`。
  下载端点在文件未就绪时返回 **HTTP 202 + 空 body**（已实测，见
  `.claude/notes/notes.md`）。
- **HuggingFace** 在 repo 内按 commit SHA + LFS OID(sha256) 内容寻址，但
  `org/name` 命名空间可改名、删除、加 gating。
- **裸 HTTP** 无任何元数据保证。

结论：**digest 必须由 molhub 校验，不能信任传输成功**；上游 digest 只作对账，
molhub 的权威键统一为 sha256。

## Design

### 分层与依赖方向

```
molhub/registry/
  locator.py      Locator          "scheme://path" 解析，冻结值对象
  digest.py       Digest           算法 + hex，构造与比对
  remote.py       RemoteFile       url / size / upstream_digest / filename
  driver.py       Registry         驱动协议
  drivers.py      Drivers          驱动集合（entry point 发现、scheme 查找）
  blobs.py        BlobStore        内容寻址缓存
  fetcher.py      Fetcher          按序 fallback + 校验 + 原子落盘
  drivers/
    https.py      HttpsRegistry
    zenodo.py     ZenodoRegistry
    figshare.py   FigshareRegistry
    huggingface.py HuggingFaceRegistry
    molhub.py     MolHubRegistry   自建插件 registry（静态对象存储 + CDN）
```

`molhub.registry` **不得** import `molhub.dataset`。反向依赖是允许的，且是 02 的工作。

### `Registry` 驱动接口

新增平台 = 实现这一个协议 + 注册 entry point，**不改动 molhub 任何既有代码**。

```python
class Registry(Protocol):
    scheme: str                                            # "zenodo" | "hf" | ...

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        """把 locator 解析为可下载的文件列表（含上游 digest / size 若有）。"""

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        """把单个远端文件流式写入 dest。契约见下。"""

    # 可选
    def publish(self, files: Sequence[Path], target: str, meta: Mapping) -> Locator: ...
```

**硬约束**：`MolHubRegistry`（自建插件 registry）必须走同一接口，不得特例化、
不得在 `Fetcher` 里出现任何 `if scheme == "molhub"` 分支。这条由 ac-007 证伪。

驱动的查找与注册由 `Drivers` 这个**不可变集合**承担，不用自由函数：

```python
class Drivers:
    """The Registry drivers available to a Fetcher."""

    @classmethod
    def discover(cls) -> "Drivers":
        """Build the set from the ``molhub.registries`` entry-point group."""

    def with_driver(self, driver: Registry) -> "Drivers":
        """Return a **new** set with *driver* added (never mutates in place)."""

    def for_scheme(self, scheme: str) -> Registry:
        """Return the driver handling *scheme*.

        Raises:
            UnknownScheme: If no registered driver claims it.
        """
```

`with_driver` 返回新对象而非就地修改——与全局编码规范的不可变要求一致，也让
测试可以临时叠加一个假驱动而不污染进程状态。

### `fetch` 契约（不可协商）

1. 校验 HTTP status，非 200 立即抛错
2. 流式写入 `dest.with_name(dest.name + ".part")`，不整体读入内存
3. 边写边算 sha256
4. digest 不匹配 → 删除临时文件并抛错
5. 全部通过才 `os.replace` 原子改名

**最终路径上永远不出现未校验、半截或 0 字节的文件。**

### `Fetcher` 的 fallback 语义

```
for locator in locators:            # 有序，前面的优先
    try:  resolve -> fetch -> verify -> 落盘;  return
    except (网络错 / 非200 / digest 不符):  记录并试下一个
raise AllLocatorsFailed(每个 locator 的失败原因)
```

digest 不符**不重试同一 locator**，直接换下一个——它意味着该镜像内容不对。

### 缓存布局（冻结契约，见 CLAUDE.md）

```
$MOLHUB_HOME/                       默认 ~/.cache/molhub
  blobs/sha256/<前2位>/<完整hex>    内容寻址，不可变
  tmp/                              .part 文件；与 blobs 同分区以保证 rename 原子
```

Python 与未来 TS 客户端同机共享此布局、互相命中。布局由 03 的 conformance 固化。

### Reuse decision

| 现有代码 | 处置 | 说明 |
|---|---|---|
| `qm9._download`、`csv_dataset._download` | **generalize** | 两份逐字重复的安全下载 → `HttpsRegistry.fetch` 单一实现，删除重复 |
| `qm9._is_cached` | **generalize** | 基于大小的启发式 → `BlobStore` 基于 digest 的存在性判定 |
| `csv_dataset._resolve_cache_path{,_static}` | **generalize** | 两份同体函数 → `BlobStore` 路径解析 |
| `uploader/figshare.py`、`uploader/huggingface.py` | **reuse** | 是同一驱动的 publish 半边，整体搬入对应 driver 的 `publish()` |
| `dataset/protocol.py` 的 `source_id` 冒号约定 | **pattern** | 坐标字符串沿用同一风格，但正式语法在 02 定义 |

`molhub.uploader` 保留为薄 shim 转发到 driver 的 `publish`，保两个小版本后删除。

## 用户侧 API 示例

```python
from pathlib import Path
from molhub.registry import Fetcher, Digest

fetcher = Fetcher()            # 默认驱动 + $MOLHUB_HOME 缓存

# 一个制品挂多个来源，按序 fallback；digest 由调用方给（02 起改由 manifest 给）
path: Path = fetcher.fetch(
    locators=[
        "zenodo://14980914/LAMALAB_CURATED_Tg_structured.csv",
        "hf://MolCrafts/tg-dataset/Tg.csv",
        "https://mirror.example.org/Tg.csv",
    ],
    digest=Digest.sha256("ce2c7b2a879450cbbfff4d7ccea648f9…"),
)
# 第二次调用直接命中缓存，不发网络请求
assert fetcher.fetch(locators=[...], digest=...) == path
```

扩展一个新平台（第三方也能做，无需改 molhub）：

```python
# mypackage/dataverse.py
from molhub.registry import Registry, RemoteFile, Locator

class DataverseRegistry:
    scheme = "dataverse"

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        meta = httpx.get(f"https://{locator.host}/api/datasets/{locator.path}").json()
        return [RemoteFile(url=f["url"], size=f["size"],
                           upstream_digest=f"md5:{f['md5']}", filename=f["name"])
                for f in meta["files"]]

    def fetch(self, remote, dest): ...      # 或继承 HttpsRegistry 复用其实现

# pyproject.toml
# [project.entry-points."molhub.registries"]
# dataverse = "mypackage.dataverse:DataverseRegistry"
```

发布（uploader 归位后）：

```python
from molhub.registry import Drivers

zenodo = Drivers.discover().for_scheme("zenodo")
locator = zenodo.publish([Path("data.csv")], target="new-record",
                         meta={"title": "My dataset", "license": "CC0-1.0"})
```

测试里临时叠一个假驱动，不污染进程全局：

```python
drivers = Drivers.discover().with_driver(FakeRegistry())   # 返回新集合
fetcher = Fetcher(drivers=drivers)
```

## Files

| 动作 | 路径 |
|---|---|
| new | `src/molhub/registry/{__init__,locator,digest,remote,driver,drivers,blobs,fetcher}.py` |
| new | `src/molhub/registry/drivers/{__init__,https,zenodo,figshare,huggingface,molhub}.py` |
| new | `tests/test_registry/**`（镜像 src） |
| edit | `src/molhub/dataset/{qm9,csv_dataset}.py` — 删除本地 `_download`/`_is_cached`/缓存路径，改用 `Fetcher` |
| edit | `src/molhub/uploader/{figshare,huggingface}.py` — 降级为 shim |
| edit | `pyproject.toml` — 声明 `molhub.registries` entry point 组 |

## Tasks

- [x] Add `Locator` 值对象与 `scheme://path` 解析（含非法输入拒绝）
- [x] Add `Digest` 值对象（sha256 构造、流式更新、常数时间比对、`md5:`/`sha256:` 前缀解析）
- [x] Add `RemoteFile` 值对象
- [x] Add `BlobStore`：`$MOLHUB_HOME` 解析、`blobs/sha256/<ab>/<hex>` 路径、`has()`/`put()`/`path_for()`
- [x] Add `Registry` 协议
- [x] Add `Drivers` 不可变集合：`discover()` / `with_driver()` / `for_scheme()`
- [x] Add `HttpsRegistry`，实现 fetch 五步契约（status / 流式 / 边写边算 / 不符即弃 / 原子改名）
- [x] Add `ZenodoRegistry.resolve`（`/api/records/<id>` → files + checksum）
- [x] Add `FigshareRegistry.resolve`（`/v2/articles/<id>/files` → supplied_md5）
- [x] Add `HuggingFaceRegistry.resolve`（repo/revision/path → LFS OID）
- [x] Add `MolHubRegistry`（静态 JSON 清单 + CDN 直链），不得特例化
- [x] Add `Fetcher`：按序 fallback、失败聚合为 `AllLocatorsFailed`、缓存命中短路
- [x] Refactor `qm9.py` / `csv_dataset.py` 的重复 `_download` 收编到 `HttpsRegistry`
- [ ] Refactor `qm9.py` / `csv_dataset.py` 改用 `Fetcher`（**阻塞于 02**：`Fetcher` 要求 digest，而 digest 来自 manifest）
- [ ] Refactor `uploader/*` 搬入对应 driver 的 `publish()`，顶层保留 shim
- [x] Add `tests/test_registry/**` 单测，全部用 mock 驱动，零真实网络

## Testing

- 单测全部离线：`urlopen` 用假响应对象替换（沿用 `tests/test_dataset/test_qm9.py`
  已有的 `_FakeResponse` 模式）。
- 必须覆盖的失败路径：HTTP 202、HTTP 500、传输中断、digest 不符、第一个 locator
  失败第二个成功、全部失败。
- `BlobStore` 布局用真实临时目录断言精确路径字符串。
- 「不得特例化」由一条静态测试守：grep `fetcher.py` 与 `driver.py` 不含
  `"molhub"` 字面量分支。

## Out of scope

- 坐标语法、manifest、索引（→ 02）
- 语言中立 conformance 套件（→ 03）
- 字节内容解析、`Frame` 构造、`TargetSchema`
- 断点续传、并发分片下载、限速
- 私有制品鉴权（除各平台已有 token 透传外）
