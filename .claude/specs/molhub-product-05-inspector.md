---
slug: molhub-product-05-inspector
status: in-progress
created: 2026-08-09
last_audited: 2026-08-09
chain: molhub-product
position: 5
depends_on:
  - molhub-product-01-registry-contract
  - molhub-product-02-clients-transport
  - molhub-product-04-web-catalog-design
scope_layer: Web Inspector, MolVis integration and derived data plane
lifecycle: durable
---

# MolHub Inspector — 从 Registry 到结构—属性探索

## Summary

MolHub Inspector 让用户从一个 registry coordinate 直接进入科学数据检查工作台：选择
artifact role 和 frame，在 MolVis 中查看结构或轨迹，在 MolPlot 中浏览属性分布或低维
地图，并在两者之间保持双向选择。

Chemiscope 的关键产品模式是“结构/原子环境 ↔ property map”的联动，而不只是 3D
viewer。MolHub 采用这个模式，但不复制 Chemiscope 的代码、文件格式或界面。MolHub
的差异化是：stable version、upstream provenance、ordered sources、跨 SDK 获取、
trajectory streaming、可分享检查状态，以及 MolVis 的 agent/human selection loop。

参考：

- <https://chemiscope.org/docs/getting-started/properties.html>
- <https://chemiscope.org/docs/getting-started/json-format.html>
- <https://chemiscope.org/docs/examples/2-structure_map.html>

## Product ownership

| 能力 | 所有者 |
|---|---|
| coordinate、role、version、provenance、Inspect route | MolHub |
| 3D/2D rendering、trajectory、selection、measure、RPC | MolVis |
| linked scatter/line/histogram | MolPlot |
| normalized structures/trajectory/observables | MolRec |
| parsing、PCA/k-means、scientific kernels | MolRS/WASM |
| approved source metadata | molhub-registry |
| derived preview/index/chunks | MolHub data plane，非 registry |

MolHub Web 直接依赖 `@molcrafts/molvis-stage` 和 `@molcrafts/molplot` 的公开 package
surface。禁止复制 MolVis source，禁止把完整 `molvis/page` iframe/嵌入 MolHub——它会
带来第二套 shell、tokens、navigation 和交互语言。

如果 Inspector 需要 MolVis 当前没有的通用能力，例如 `HttpRangeSource`，先在 MolVis
实现并发布，再由 MolHub 升级依赖。

## Route and URL state

规范路由：

```text
/molhub/inspect/<kind>/<namespace>/<name>/<version>
  ?role=train_300K
  &frame=42
  &x=frame
  &y=energy
  &color=temperature
  &selection=...
```

URL 至少保存 coordinate、role、frame 和图表轴。选择集只有在能紧凑、稳定地编码时
进入 URL；大 selection 通过显式“share state”产生短期或内容寻址 state document，
不能把数千 atom ids 塞进 query。

刷新或分享 URL 必须恢复同一 artifact role、frame 和 plot selection。URL 不保存临时
签名下载地址。

## Layout and interaction

Inspector 是 MolHub 的 full-workspace route，但继续使用 MolHub header、tokens 和
typography。Desktop 默认结构：

```text
┌──────────────── coordinate / role / provenance / share ────────────────┐
│                                                                        │
│  structure-property map / table          MolVis viewer                 │
│  filters, axes, color, selection          frame, selection, measure     │
│                                                                        │
├──────────────── properties / trajectory / loading and errors ─────────┤
```

窄屏按 viewer → frame controls → property/map 的任务顺序堆叠，并允许快速切 tab。不能把
desktop 两栏简单缩窄到不可操作。

必须双向联动：

- 点击 plot point 加载对应 frame，并高亮 active point；
- 播放/切换 trajectory frame 更新 plot highlight；
- 选择 atom 时显示 atom-level properties；
- 从 atom/environment map 选择点时在 MolVis 中居中并高亮对应环境；
- filter 隐藏点不改变 frame id，避免分享链接漂移；
- loading、indexing、cancel、parse error、CORS 和 unsupported format 都有明确状态。

## Data paths

Inspector 有两条数据路径，按 artifact 体积和格式选择，不能强迫所有数据先转换。

### Direct path

适合浏览器可解析、体积可控的单文件：

```text
manifest locator → resolved HTTPS → fetch Blob/stream → MolVis/MolRS parser
```

首个 vertical slice 使用：

```text
dataset:molcrafts/3bpa@v1
role: train_300K
format: Extended XYZ
size: about 1.5 MB
```

MVP 可以完整读取 `train_300K` Blob；随后 remote streaming 应使用 HTTP range 或
ReadableStream，不将大 trajectory 转成巨型 JS string。

### Derived path

适合 archive、NPZ、超大 trajectory 或无法随机访问的来源：

```text
upstream artifact
  → trusted indexing/conversion job
  → MolRec/Zarr + property/index metadata + provenance digest
  → static/R2 derived store
  → HTTP chunk/range reader
  → MolVis + MolPlot
```

Derived output 必须记录 source coordinate、role、source digest/size、converter version、
MolRec schema version 和生成时间。Source manifest/version 改变时生成新派生 key，不能
覆盖成无法追溯的“latest”。

Derived store 不是 authoritative registry。删除后可以从 source + converter 重建；Web
必须把它标为 preview/derived data，而非声称上游原始格式就是 MolRec。

## Manifest and inspection descriptor

Manifest 可以增加字节语义字段：

```yaml
artifacts:
  - role: train_300K
    filename: train_300K.xyz
    format: extxyz
    media_type: chemical/x-xyz
```

是否同时保留 `format` 和 `media_type` 要通过 schema proposal 决定；MVP 不为赶页面在
Web 中建立长期 filename allowlist。

Inspector 的生成信息使用独立 derived descriptor，例如：

```json
{
  "schema_version": 1,
  "source": {
    "coordinate": "dataset:molcrafts/revmd17@v4",
    "role": "aspirin",
    "digest": "md5:..."
  },
  "record": {
    "format": "molrec-zarr-v3",
    "url": "...",
    "frames": 100000
  },
  "properties": [
    {"name": "energy", "target": "structure", "unit": "kcal/mol"},
    {"name": "forces", "target": "atom", "unit": "kcal/(mol angstrom)"}
  ]
}
```

该 descriptor 是 builder/indexer 产物，不手写进 `molhub-registry`。

## Delivery phases

### Phase 0 — Production baseline

先完成 product-03 的 production Web/API/D1/GitHub 提交流程。Inspector 不得成为延迟
现有提交功能上线的理由。

### Phase 1 — Contract and compatibility spike

- 为 artifact format/media type 写 schema proposal 和 conformance cases；
- 建 `Inspectability` 纯函数：supported direct / supported derived / unsupported + reason；
- 验证 3BPA raw URL 的 CORS、内容、ExtXYZ properties 与 MolVis loader；
- 记录 MolVis 当前远程 loading、Zarr 和 plotting 的能力/缺口；
- 详情页只对真正兼容的 role 显示 Inspect。

### Phase 2 — 3BPA vertical slice

- 新增规范 route 和 route-level lazy bundle；
- role switcher，默认 `train_300K`；
- MolVis 轨迹、frame scrub/play、structure info；
- frame index ↔ energy plot；
- point/frame 双向联动；
- URL restoration、copy link、coordinate/provenance；
- cancel、progress、unsupported/CORS/parse errors；
- desktop/mobile、light/dark、keyboard 验收。

不要求先完成 PCA。3BPA 首版只有 energy 一个自然 graph-level scalar 时，`frame index ×
energy` 比假造第二个 descriptor 更诚实。

### Phase 3 — Remote data primitives in MolVis

- `HttpRangeSource` 或等价 remote random-access abstraction；
- HTTP Range capability detection 与 full-download fallback policy；
- remote MolRec/Zarr chunk reader，不把整个目录 base64 materialize；
- AbortSignal、加载进度、LRU/OPFS cache 和内存预算；
- package-level tests，MolHub 只做 integration tests。

### Phase 4 — Structure-property explorer

- 任选 numeric properties 作为 x/y/color/size；
- histogram/table/filter；
- PCA + optional k-means；
- structure-level 与 atom/environment-level target 切换；
- plot selection ↔ MolVis atom/environment selection；
- 保存/恢复 visualization state。

PCA 输入是明确选择的 descriptors；计算方法、seed 和缺失值规则进入可分享 state，避免
同一链接每次得到不同图。

### Phase 5 — Dataset adapters

按数据形状分别推进：

| Dataset | 问题 | 首选路径 |
|---|---|---|
| 3BPA | 小型 ExtXYZ | direct |
| revMD17 | 67–175 MB NPZ，MolVis 无 NPZ reader | trusted conversion → MolRec/Zarr |
| QM9 | 86 MB tar.bz2，133k structures | archive indexing + sampled/remote MolRec |
| Polymer Tg | CSV + PSMILES，不是 trajectory | table/filter + MolVis sketch/generate3D adapter |

不同 adapter 必须汇合到同一 MolRec/property contract，不能在 route 中写四套 dataset
专用 UI。

### Phase 6 — Agent and comparison workflows

- MolVis RPC 操作 live scene；
- 用户 selection 返回结构化 frame/atom context；
- 可审计 snapshot 和操作记录由 MolHub host 保存；
- 比较同 artifact 多版本或多个 pinned frames；
- 从 Inspector 一键复制 Python/TS reproducible loading snippet。

## Performance and safety

- Home/Explore/普通 detail 不加载 BabylonJS/MolVis/MolPlot；
- MolPlot Web 图表只使用 Canvas renderer，不生成 SVG mark tree；静态预渲染编译使用
  Vega 官方 DOM Canvas adapter，不引入仅服务端栅格化才需要的原生 `node-canvas`；
- Inspector 在取得 format/descriptor 前不下载 artifact body；
- 所有 remote operations 可取消，route change 后不得继续更新已卸载 scene；
- 大文件不通过 submission Worker 代理；data plane 有独立缓存和 CORS policy；
- 默认只加载所需 role，不因打开 aspirin 自动取回 revMD17 全 archive；
- parser/worker failure 不留下错误 OPFS cache；
- 页面显示 source coordinate 和 derived provenance，用户能区分 source 与 preview。

## Testing

- pure：inspectability、URL state、descriptor schema、property mapping；
- component/browser：viewer lifecycle、point/frame linking、theme、keyboard；
- network integration：range supported/unsupported、abort、CORS、corrupt chunk；
- end-to-end：从 3BPA detail 点击 Inspect，恢复深链接并切 role/frame；
- performance：assert non-inspector chunk graph 不包含 MolVis/Babylon；
- cross-repo：MolVis public package contract 测试，不依赖私有 source path。

## Out of scope

- 第一版复刻 Chemiscope 的全部 JSON/settings surface；
- 在浏览器计算需要 GPU 集群的大型 descriptor；
- 自动上传或永久保存用户拖入的本地文件；
- 把 MolHub 变成通用 MolVis editor；
- 为不支持的格式显示一个会失败的 Inspect 按钮。
