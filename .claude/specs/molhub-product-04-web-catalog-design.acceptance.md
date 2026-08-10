---
spec: molhub-product-04-web-catalog-design
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "技术栈固定"
    type: code
    pass_when: "Web 使用 TanStack Start + Rsbuild + Rstest，typecheck 与 Biome 通过"
    status: passed
    last_checked: 2026-08-09
  - id: ac-002
    summary: "统一 token 驱动 light/dark"
    type: visual
    pass_when: "关键组件不含任意产品颜色值，primary/outline/state controls 在 light/dark 与 hover/focus/disabled 下均达到可读对比"
    status: pending
    last_checked: 2026-08-09
  - id: ac-003
    summary: "首页文案清楚"
    type: ux
    pass_when: "首屏是 MolHub + 一句普通语言说明；禁用口号与抽象 CTA 不存在"
    status: passed
    last_checked: 2026-08-09
  - id: ac-004
    summary: "Registry 内容可发现"
    type: runtime
    pass_when: "search 可匹配 coordinate/title/description/role/filename/targets，kind filter 不改变原 registry order"
    status: passed
    last_checked: 2026-08-09
  - id: ac-005
    summary: "每个 entry 预渲染"
    type: build
    pass_when: "production build 为 snapshot 中每个 coordinate 生成可访问 detail page，无 runtime registry fetch"
    status: passed
    last_checked: 2026-08-09
  - id: ac-006
    summary: "代码片段与 SDK 同步"
    type: runtime
    pass_when: "Python、TypeScript、CLI snippet 使用 canonical coordinate，并通过对应 SDK/CLI smoke test"
    status: passed
    last_checked: 2026-08-09
  - id: ac-007
    summary: "Inspector 不污染 catalog bundle"
    type: performance
    pass_when: "home/explore initial chunk graph 不包含 BabylonJS、MolVis stage 或 MolPlot；只在 inspect route 加载"
    status: passed
    last_checked: 2026-08-09
  - id: ac-008
    summary: "关键页面有视觉回归"
    type: visual
    pass_when: "home、explore、detail、submit 在 desktop/mobile 与 light/dark 均有可审查截图基线"
    status: pending
    last_checked: 2026-08-09
out_of_scope:
  - "文档站"
  - "社交和排行榜"
---

# Acceptance — Web Catalog

单元测试无法证明视觉一致。ac-002 和 ac-008 需要真实浏览器截图与人工审查，重点覆盖
此前出现过的深色按钮文字对比、卡片密度和标题/正文排版问题。

NGC 只作为 catalog 信息密度参考。验收不能以“长得像 NVIDIA”作为标准，而应检查用户
是否能在不阅读说明的情况下识别 artifact、版本、license、来源和下一步操作。
