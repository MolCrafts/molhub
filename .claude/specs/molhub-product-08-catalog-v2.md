---
slug: molhub-product-08-catalog-v2
status: proposed
created: 2026-08-09
chain: molhub-product
position: 8
depends_on:
  - molhub-product-01-registry-contract
  - molhub-product-04-web-catalog-design
  - molhub-product-05-inspector
  - molhub-product-07-live-registry-distribution
scope_layer: catalog information architecture, artifact families, discovery metadata and UI
lifecycle: durable
---

# Catalog 2.0 — Artifact Families、科学发现与诚实的产品界面

## Summary

Catalog 2.0 把 MolHub 从少量 manifest 的静态陈列页升级成可工作的科学制品目录。用户
应能先按任务和数据形状缩小范围，再判断版本、格式、规模、license、provenance 和是否
可 Inspect，最后复制稳定 coordinate 或进入 Inspector。

Catalog 不以空分类制造产品规模感，也不使用下载量、评分或没有数据来源的“热门”排序。
当 model/plugin 尚无足够 metadata contract 或 approved entries 时，产品必须诚实地将其
标为 experimental/coming later，而不是在主要导航中展示 `0`。

## Launch content gate

Catalog 2.0 production launch 至少包含 20 个经过审核的 dataset families，并覆盖：

- 小型 browser-readable structure/trajectory；
- 大型 archive/NPZ，需要 derived inspection；
- table/property dataset；
- 多 role/split dataset；
- 不同 source platform、license 和 target shape。

数字只是最低“不是 demo”的发布门，不是长期 KPI。不得为了凑数降低 DOI、pinned locator、
size/digest 或 description 质量。每个 entry 必须有用户可理解的 title/description、明确
format/media type 和至少一个可操作 usage snippet。

一个 kind 只有在同时满足以下条件时才进入首页与主导航：

1. 有该 kind 的 typed profile contract；
2. 至少三个不同 family 的 approved production entries；
3. detail、usage 与 submission UI 能正确解释这些字段。

## Kind profiles

core manifest 继续拥有 coordinate、title、license、DOI、artifacts、targets。Dataset、model、
plugin 的差异通过 discriminated `profile` contract 表达，不能把所有可能字段堆成一个
mega-object。

### Dataset profile

至少能描述：domain/task tags、sample/structure count（已知时）、element coverage（适用时）、
split/role vocabulary 和 citation authors。科学结构/observable 的完整语义仍归 MolRec，
profile 只服务发现，不复制 record schema。

### Model profile

至少能描述：framework/format、task、supported elements、input/output contract、training
dataset coordinates、checkpoint roles 和 published evaluation evidence。训练数据引用必须是
pinned MolHub coordinate；自由文本名字不能替代 provenance。

### Plugin profile

至少能描述：host product、host version range、entry points、capabilities、install package 和
required permissions。Catalog 不执行 plugin，也不把 plugin metadata 当成安全审计结论。

引入 profile 前必须走 product-01 的 schema evolution gate。若 required semantics 会使 v1
manifest 失效，应提升 schema version 并提供 migration/conformance vectors，不原地收紧。

## Artifact family and versions

Registry entry 仍对应一个不可变 coordinate。Catalog 在 read model 中把
`kind:namespace/name@version` 聚合成 family `kind:namespace/name`：

- Explore 默认每个 family 展示 head version，可显式切换“全部版本”；
- head 是 catalog navigation 信息，不产生可传给 SDK 的无版本 coordinate；
- detail 顶部提供 version selector，分享/复制始终保留具体 version；
- 旧版本显示“有更新版本”信息，但继续可访问、可 fetch；
- version comparison 展示 metadata、roles、format、size、targets、sources 和 published
  digest 的变化，不下载原始 bytes 做隐式 scientific diff。

Version 排序必须定义并测试。不能假设所有 upstream version 都是纯整数；无法语义解析的
label 使用稳定 code-point order，并在 read model 中允许显式 head override proposal，不能
擅自将 `beta` 判断成比 `10` 更新。

## Discovery contract

Explore 的 URL state 至少包括：

```text
q, kind, namespace, license, source, format, inspectable, target, versions, view, sort
```

需要支持：

- free text：title、description、coordinate、role、filename、target、profile tags；
- exact/filter：kind、namespace、license、source scheme、format、inspectability；
- target 搜索区分 graph/atom scope，但普通用户可以只按名称搜索；
- card/list 切换，selection 和 filters 在刷新/分享后恢复；
- deterministic default order；无下载量时不伪造 popularity；
- mobile filters 使用 drawer/sheet，结果阅读顺序不被筛选控件打断。

当规模尚小，search 继续是静态 read model；达到需要服务端搜索的证据阈值前不增加数据库。
Registry 增长时可以生成轻量 catalog index 与 route chunks，但每个 detail 仍可预渲染，且
不得让完整 Inspector/validator/manifest payload 进入 home initial bundle。

## Home information architecture

首页首屏保持一个任务：理解 MolHub 并开始搜索。推荐结构：

1. `MolHub` + `Find, inspect, and fetch versioned molecular data.`；
2. primary search；
3. `Ready to inspect`：只来自 shared Inspectability 的真实兼容 entries；
4. curated dataset families / data shapes；
5. submit/import 入口。

不显示无内容 kind、不显示没有来源的“recent/popular”数字、不在首页加载 3D canvas。缩略图
如存在，必须是 build-time/derived preview，有 source coordinate 和 deterministic fallback；
装饰性随机 molecule 不得暗示是该 dataset 的真实内容。

## Card and detail hierarchy

### Catalog card/list row

信息顺序：

1. human title；
2. namespace/name + pinned version；
3. kind、license、targets/profile tags；
4. roles/size/format/inspectability；
5. primary `Inspect`（兼容时）或 `View details`，以及 `Copy coordinate`。

Card 整体可点击时，内部 filters/actions 必须继续键盘可达且不产生 nested interactive
冲突。颜色不能是 kind/inspectability 的唯一提示。

### Detail

详情页顶部优先显示 title、coordinate、version selector、description 和 primary actions：

- Inspect default compatible role；
- Copy coordinate / Python / CLI；
- View upstream。

长内容组织为 `Overview / Files / Usage / Provenance`，或同等清楚的 anchored sections。
Files 保留每个 role 的独立 Inspect/Fetch 信息；top-level Inspect 只是合理默认值，不隐藏
role 选择。Provenance 清楚区分 published digest、size-only verification、single source 和
derived preview，不把合法的“平台未发布 digest”渲染成安全事故。

## Visual and accessibility completion

- 保留 MolCrafts forest/cream tokens，不做与现有产品无关的品牌重画；
- 提升 title/coordinate 层级，减少所有内容同尺寸白卡片的 dashboard 感；
- 以真实 20+ entry 数据验证 desktop density 和长 title/target；
- 保存 home/explore/detail 的 desktop/mobile × light/dark screenshot baseline；
- keyboard-only 完成 search、filters、copy、version switch、Inspect；
- 自动 contrast/axe 检查之外仍人工审查 focus、truncation、empty/error/loading；
- home/explore initial JS 与 CSS 建立预算，registry 增长不能线性拖入 detail/Inspector payload。

## Delivery phases

### Phase 1 — Honest catalog

- zero-kind navigation/copy；
- title-first cards、top-level Inspect；
- visual regression matrix；
- family/head projection 使用现有 entries 验证。

### Phase 2 — Content and discovery

- 20+ curated datasets；
- format/inspectability/target/source facets；
- list/card/mobile filters 和 URL restoration。

### Phase 3 — Families and comparison

- version selector、all-version view、superseded state；
- metadata comparison；
- stable head semantics tests。

### Phase 4 — Kind expansion

- schema proposal + migration；
- model/plugin typed profiles；
- 每个 promoted kind 的真实 entries、detail、usage 和 submission UI。

## Out of scope

- 下载量、评分、评论、排行榜或推荐 feed；
- 无版本 coordinate；
- 在 Web 中手写第二份 registry catalog；
- 自动运行不受信任 model/plugin；
- 用通用 profile mega-object复制 MolRec/MolVis semantics。
