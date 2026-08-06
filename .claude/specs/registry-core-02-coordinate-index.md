---
slug: registry-core-02-coordinate-index
status: in-progress
created: 2026-08-06
chain: registry-core
position: 2
depends_on: [registry-core-01-transport]
scope_layer: L2 resolution
---

# registry-core-02-coordinate-index — 坐标语法、manifest schema 与静态索引

## Summary

建立 L2 解析层：一套 **molhub 拥有且永久稳定的坐标语法**，一份**语言中立的
manifest / index schema**，一个把坐标解析为 locator 列表 + digest 的 `Molhub`
门面，以及一个**独立于客户端仓的静态索引仓** `molhub-index`。

核心断言：**数据集不是代码，是 manifest**。新增一个数据集 = 往索引仓提一份
YAML 的 PR，**molhub 不发版**。现有 4 个数据源的硬编码 URL 全部迁入 manifest。

## Domain basis

同 01，无物理内容。设计约束来自本次讨论确立的两条事实：

1. **DOI 不是字节。** DOI 解析到的是记录，仍需 `DOI → API → 文件列表 → 直链`。
   坐标层的价值不是「防链接腐烂」（上游标识确实稳定），而是把异构的上游标识
   归一化为一个可寻址、可版本化、可挂多源的东西。
2. **上游 digest 类型不一。** Zenodo 给 md5，HF 给 sha256(LFS OID)，Figshare 给
   supplied_md5。manifest 同时记 `upstream_digest`（原样，用于与上游对账）和
   `sha256`（molhub 权威键，首次取回后由 CI bot 计算并锁定）。缓存是内容寻址的，
   键必须统一。

## Design

### 坐标语法（冻结契约）

```
<kind>:<namespace>/<name>@<version>
        └── dataset | model | plugin

dataset:molcrafts/qm9@v2
model:molcrafts/mace-mp-0@1.0
plugin:molcrafts/molvis-render@0.3.1
```

简写 `qm9@v2` 在默认 kind(`dataset`) + 默认 namespace(`molcrafts`) 下解析。
版本不可省略——省略会让「可复现」这个卖点落空，且日后再收紧是破坏性变更。

`namespace` / `name` 限定 `[a-z0-9][a-z0-9-]*`；`version` 限定
`[A-Za-z0-9][A-Za-z0-9._-]*`。语法由 schema 中的 pattern 固化，两端共用。

### 序列化格式：YAML

manifest、index、schema 一律 **YAML**。理由是这些文件的第一读者是人：贡献者
手写、reviewer 在 PR 里读。YAML 允许注释（可以就地写下「为什么挂这个镜像」），
不会因为漏个逗号整份失效。

schema 本身是 **JSON Schema 规范**，只是**用 YAML 书写**（`manifest.schema.yaml`）——
JSON Schema 是数据模型，不绑定序列化语法，任何通用校验器读进来都一样。

> **一处需要你拍板的代价**：浏览器端（04/05）要读 index 就得带一个 YAML 解析器
> （约 30–40 KB gzip），而 JSON 是 `JSON.parse` 零成本。构建脚本 `build_index`
> 因此**同时**产出 `index.yaml`（人读、可 diff）与 `index.json`（机器读、供浏览器）
> ——两者由同一份 manifest 生成，不存在漂移风险。若你要求浏览器也只读 YAML，
> 删掉 json 产物即可，代价是首屏多几十 KB。

### Manifest 格式

```yaml
schema_version: 1
kind: dataset
namespace: molcrafts
name: qm9
version: v2

title: QM9 — 134k small organic molecules
license: CC0-1.0
citation: 10.1038/sdata.2014.22

artifacts:
  - role: main
    filename: qm9.tar.bz2
    sha256: "…"                 # 必填；CI 拒绝缺失，bot 自动回填
    size: 82000000
    upstream_digest: "md5:…"    # 与上游对账用，可选
    locators:                   # 有序 fallback
      - figshare://3195389
      - hf://MolCrafts/qm9/qm9.tar.bz2

  - role: exclude
    filename: qm9_exclude.txt
    sha256: "…"
    locators:
      - figshare://3195404      # 就是这个返回 202 的端点；digest 现在会拦住它

targets:
  graph_level: [A, B, C, mu, alpha, homo, lumo, gap, r2, zpve, U0, U, H, G, Cv]
  atom_level: []
```

`targets` 是**声明性元数据**，供前端展示与下游自行使用；本链**不**据此解析字节
（那是 L3，明确 out of scope）。

### 索引仓 `molhub-index`

```
molhub-index/
  schema/manifest.schema.yaml      唯一真相源，语言中立
  schema/index.schema.yaml
  artifacts/dataset/molcrafts/qm9/v2.yaml
  artifacts/plugin/molcrafts/…
  conformance/                     ← 03 使用
  .github/workflows/validate.yml   schema 校验 + digest 存在性 + locator 探活
  scripts/build_index.py           汇总 → dist/index.yaml + dist/index.json
```

**必须独立于客户端仓**：外部贡献者提 manifest 不应需要客户端写权限，也不该触发
库发版。当前 `qm9.py` 把上游 URL 写成 Python 常量——改一个链接要发一次版，
正是要消除的形态。

> 命名注意：本机已有 `molcrafts-index` 仓，那是 **molcrafts.org 落地页**，
> 与本 spec 的 `molhub-index` 无关，勿混。

### 类型（全部 OOP）

```python
class Coordinate:                     # 值对象，冻结
    @classmethod
    def parse(cls, text: str) -> "Coordinate": ...
    @property
    def canonical(self) -> str: ...   # 规范化全称字符串

class Artifact:                       # manifest 里的一个制品
    role: str; filename: str; sha256: Digest
    locators: tuple[Locator, ...]

class Manifest:                       # 一份 manifest
    @classmethod
    def from_yaml(cls, text: str) -> "Manifest": ...   # 含 schema 校验
    coordinate: Coordinate
    artifacts: Mapping[str, Artifact]  # role -> Artifact

class Index:                          # 一批 manifest 的集合
    @classmethod
    def load(cls, source: "IndexSource") -> "Index": ...
    def get(self, coord: Coordinate) -> Manifest: ...
    def search(self, *, kind=None, query=None) -> list[Manifest]: ...

class IndexSource:                    # 索引从哪来
    @classmethod
    def resolve(cls) -> "IndexSource": ...   # $MOLHUB_INDEX → CDN → 内置快照

class Molhub:                         # 门面，用户唯一需要认识的类
    def __init__(self, *, index=None, fetcher=None) -> None: ...
    def resolve(self, coord: str) -> Manifest: ...
    def fetch(self, coord: str) -> dict[str, Path]: ...
    def search(self, *, kind=None, query=None) -> list[Manifest]: ...
```

`Molhub` 只做组合：`Index` 查 manifest，01 的 `Fetcher` 取字节。**它自己不发 HTTP**
（由 ac-007 证伪）。

### CI bot 的两个职责

- **digest 自动抓取**：manifest 提交时若 `sha256` 缺失，bot 从上游 API 取
  （Zenodo `files[].checksum`、HF LFS OID、Figshare `supplied_md5`），实际下载一次
  算出 sha256 并回填 PR。**人不手写 digest。**
- **夜间巡检**：重新解析全部 locator，比对 sha256。上游若真如预期稳定，它永远绿灯、
  零成本；若不稳定，是它先报警而不是用户的数据集静默出错。

### Reuse decision

| 现有代码 | 处置 | 说明 |
|---|---|---|
| 01 的 `Fetcher` / `Digest` / `Locator` / `Drivers` | **reuse** | `Molhub.fetch` 直接组合，不重新实现取回 |
| `qm9._DEFAULT_URL` / `_EXCLUDE_URL`、`revmd17.BASE_URL` | **generalize** | 硬编码常量 → manifest 的 `locators` 数组 |
| `qm9.SOURCE_VERSION`（`"v2"`）| **generalize** | 临时版本令牌 → 坐标的 `@version` 段 |
| `dataset/protocol.py` 的 `source_id` | **reuse** | 保留其协议地位；实现改为返回规范坐标字符串 |
| `revmd17._MOLECULES` 名→文件名表 | **generalize** | 10 个分子各成一个 manifest |
| `dataset/meta.py` 的 `Targets` / `MetaCodec` | **reuse** | L3 侧不受本 spec 影响，原样保留 |

现有 `QM9Source(root)` 等构造签名**保持不变**，内部改为经 `Molhub` 取回。

## 用户侧 API 示例

```python
from molhub import Molhub

hub = Molhub()

paths = hub.fetch("dataset:molcrafts/qm9@v2")
# {"main": PosixPath("~/.cache/molhub/blobs/sha256/ab/abcd…"),
#  "exclude": PosixPath("~/.cache/molhub/blobs/sha256/cd/cdef…")}
# 已 digest 校验、已进内容寻址缓存

info = hub.resolve("qm9@v2")                # 简写等价于全称
print(info.title, info.license, info.citation)
print(info.targets.graph_level)             # ('A', 'B', ..., 'U0', ...)
print(info.artifacts["main"].sha256)
```

浏览与检索（CLI、TS 客户端、前端共用同一份索引）：

```python
for m in hub.search(kind="dataset", query="md17"):
    print(m.coordinate.canonical, "—", m.title)
# dataset:molcrafts/revmd17-aspirin@1 — revMD17 aspirin trajectory
# dataset:molcrafts/revmd17-benzene@1 — revMD17 benzene trajectory
```

CLI 用 **typer**（`molhub.cli:app`，`[project.scripts] molhub = "molhub.cli:app"`）：

```bash
$ molhub search md17
dataset:molcrafts/revmd17-aspirin@1   revMD17 aspirin trajectory      CC-BY-4.0
dataset:molcrafts/revmd17-benzene@1   revMD17 benzene trajectory      CC-BY-4.0

$ molhub info dataset:molcrafts/qm9@v2
$ molhub fetch qm9@v2 --into ./data
$ molhub cache verify                   # 重算本地 blob 的 sha256，报告损坏
$ molhub --install-completion           # typer 自带
```

既有代码零改动地继续工作：

```python
from molhub.dataset import QM9Source, Targets
qm9 = QM9Source("./data/qm9")     # 签名不变，内部已改走 Molhub + digest 校验
print(Targets(qm9[42])["U0"])
```

## Files

| 动作 | 路径 |
|---|---|
| new | `src/molhub/coordinate.py` — `Coordinate` |
| new | `src/molhub/manifest.py` — `Manifest`、`Artifact` |
| new | `src/molhub/index.py` — `Index`、`IndexSource` |
| new | `src/molhub/molhub.py` — `Molhub` 门面 |
| new | `src/molhub/cli.py` — typer app |
| edit | `src/molhub/__init__.py` — 导出 `Molhub` |
| edit | `pyproject.toml` — 加 `typer`、`pyyaml`；`[project.scripts] molhub` |
| new | `tests/test_coordinate.py`、`test_manifest.py`、`test_index.py`、`test_molhub.py`、`test_cli.py` |
| edit | `src/molhub/dataset/{qm9,revmd17,threebpa,csv_dataset}.py` — 改经 `Molhub` |
| new(外仓) | `molhub-index/`：schema、manifest、validate 工作流、build 脚本 |

## Tasks

- [x] Add `Coordinate`（`parse` / `canonical` / 简写展开 / 非法输入拒绝）
- [x] Add `manifest.schema.yaml`（随包发布，jsonschema 双向一致性测试）
- [ ] Add `index.schema.yaml`（聚合索引尚不存在，待外仓）
- [x] Add `Artifact` 与 `Manifest.from_yaml`（缺 sha256 直接拒绝加载）
- [x] Add `IndexSource.resolve`：`$MOLHUB_INDEX` → CDN → 内置快照
- [x] Add `Index.load` / `Index.get` / `Index.search`
- [x] Add `Molhub` 门面（`resolve` / `fetch` / `search`），组合 01 的 `Fetcher`
- [x] Add typer CLI：`search` / `info` / `fetch` / `cache verify`
- [ ] Add 外仓 `molhub-index` 骨架 + schema + validate 工作流
- [ ] Add `build_index.py` — 同时产出 `dist/index.yaml` 与 `dist/index.json`
- [x] Add 首份真实 manifest：`dataset:molcrafts/polymer-tg@1`（Zenodo，端到端已验证）
- [ ] Add QM9 / revMD17(×10) / 3BPA(×4) 的 manifest（**阻塞**：需先取回各制品算 sha256；QM9 的 Figshare 端点当前返回 202）
- [ ] Add CI bot：digest 自动抓取回填 PR
- [ ] Add CI bot：夜间 locator 巡检 + digest 比对
- [ ] Refactor 4 个数据源改经 `Molhub`（**阻塞于上一条**：没有 manifest 就没有 digest）
- [ ] Refactor `source_id` 改为返回规范坐标字符串（**阻塞于上一条**）

## Testing

- 坐标解析用参数化表驱动，合法与非法各覆盖；非法输入的错误消息要指出哪一段不合法。
- manifest 校验用固定 YAML fixture，**含一个缺 `sha256` 的负样本**，断言被拒绝。
- 索引加载全部走 `$MOLHUB_INDEX` 指向的临时目录，测试不访问 CDN。
- `Molhub.fetch` 用 01 的假驱动（`Drivers.with_driver`），断言 role → 路径映射
  与 digest 被传递下去。
- CLI 用 `typer.testing.CliRunner`，断言退出码与输出，不起子进程。
- 数据源回归：`QM9Source` 用 01 的合成 tarball fixture，断言迁移后行为与迁移前逐位一致。

## Out of scope

- 字节内容解析、`Frame` 构造、`TargetSchema` 推导（L3，本链不做）
- TypeScript 客户端（→ 04）
- conformance 套件本身（→ 03；本 spec 只保证 schema 可被外部消费）
- 用户账号、下载量统计、网页端上传
- 索引的服务端 API（phase 1 纯静态）
