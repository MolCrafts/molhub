---
spec: molhub-product-08-catalog-v2
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "Catalog 对空 kind 保持诚实"
    type: ux
    pass_when: "零 production entries 或无 typed profile 的 kind 不出现在首页主要入口；文案不会承诺用户点开后不存在的 model/plugin catalog"
    status: pending
  - id: ac-002
    summary: "Catalog 脱离四条数据 demo"
    type: product
    pass_when: "production registry 至少有 20 个审核通过的 dataset families，覆盖 direct/derived、table、archive、multi-role 数据形状且每条 metadata 可操作"
    status: pending
  - id: ac-003
    summary: "Artifact family 与版本不破坏 pinned coordinate"
    type: runtime
    pass_when: "Explore 默认按 family 展示 head、可看全部版本；detail version switch/compare 后 URL、copy 和 snippets 始终包含具体 version"
    status: pending
  - id: ac-004
    summary: "科学发现 filters 可分享"
    type: browser
    pass_when: "query、kind、namespace、license、source、format、inspectability、target、versions、view 与 sort 刷新后恢复并产生相同有序结果"
    status: pending
  - id: ac-005
    summary: "Card 与详情任务层级正确"
    type: ux
    pass_when: "card 以 human title 为主并提供 View/Inspect 与 Copy；detail 顶部提供默认 Inspect、version 和 usage actions，长 files/provenance 可导航"
    status: pending
  - id: ac-006
    summary: "Inspectability 没有 UI 规则副本"
    type: architecture
    pass_when: "home、card、detail 使用同一 shared Inspectability；不存在按 filename、dataset name 或视觉组件各自猜 format 的分支"
    status: pending
  - id: ac-007
    summary: "Kind profile 经过受控 schema evolution"
    type: contract
    pass_when: "dataset/model/plugin profile 是 discriminated contract；breaking required semantics 提升 schema_version 并更新 validator、vectors、SDK、Web、API 与 migration docs"
    status: pending
  - id: ac-008
    summary: "Catalog 视觉和键盘矩阵完成"
    type: visual
    pass_when: "真实 production-sized registry 下，home/explore/detail 在 desktop/mobile、light/dark、keyboard-only 有审查基线且无 contrast、overflow、focus blocker"
    status: pending
  - id: ac-009
    summary: "Registry 增长不拖入重型 payload"
    type: performance
    pass_when: "home/explore initial graph 不含 Inspector、MolVis/MolPlot、完整 detail payload 或 server-only validator；20→200 entries 有记录的体积/交互预算"
    status: pending
out_of_scope:
  - "社交、评分和排行榜"
  - "无版本 latest coordinate"
  - "通用 model/plugin 执行环境"
---

# Acceptance — Catalog 2.0

内容门不能用自动生成的 fixtures 或同一 dataset 的 20 个版本满足；这里的 family 指不同
`kind:namespace/name`。质量抽检至少覆盖 title/description、DOI/license、pinned sources、
format、targets/profile 和真实 detail/usage。

视觉验收应使用生产规模 snapshot 和最长实际 metadata。用四条短 fixture 截图无法发现
facet wrapping、list density、version selector、long coordinate 和 mobile filter 问题。
