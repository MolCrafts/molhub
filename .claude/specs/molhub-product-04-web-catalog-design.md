---
slug: molhub-product-04-web-catalog-design
status: implemented
created: 2026-08-09
last_audited: 2026-08-09
chain: molhub-product
position: 4
depends_on: [molhub-product-01-registry-contract, molhub-product-03-artifact-onboarding]
scope_layer: product Web and visual language
lifecycle: durable
---

# Web Catalog、信息架构与视觉语言

## Summary

MolHub Web 是 registry 的产品界面，不是营销 landing page，也不是文档站。用户进入后
应能立即理解 MolHub、搜索 artifact、打开详情、复制使用代码、提交 manifest，并在
支持时进入 Inspector。

## Required stack

- React 19；
- TanStack Start / TanStack Router；
- Rsbuild 2，静态预渲染；
- Rstest，经 Rsbuild adapter；
- TypeScript strict、Biome；
- Tailwind CSS 4，但语义组件只使用 MolHub tokens；
- npm workspace，根 lockfile。

这些是产品约束，不允许在功能实现时悄悄换成 Next.js、Vite/Vitest 或另一套 router。

## Information architecture

```text
/molhub/                                             home
/molhub/explore                                     registry search/filter
/molhub/a/<kind>/<namespace>/<name>/<version>       artifact detail
/molhub/submit                                      manifest submission
/molhub/inspect/<kind>/<namespace>/<name>/<version> inspector (05)
```

首页只需要：MolHub、一句解释、搜索/浏览入口、少量 registry 内容。不要堆砌抽象品牌
口号、重复 CTA、无数据支撑的数字或大段“为什么我们存在”。

Explore 参考 NVIDIA NGC catalog 的信息密度：卡片/行必须优先显示标题、kind、版本、
namespace、license、targets 和 coordinate；视觉层级清楚，但不照抄 NVIDIA 品牌。

Detail page 的优先级：

1. title、coordinate、version、description；
2. Inspect（兼容时）和复制使用代码；
3. files/roles、size、source order、digest；
4. DOI、license、targets 与 provenance。

## Design language

`apps/web/app/src/styles/tokens.css` 是 Web 的语义 token 层，并与
`molcrafts-zensical-theme` 的品牌基础保持一致。组件禁止在 JSX 中散落产品颜色值。

至少定义：

- canvas/surface/tinted surface；
- foreground/muted/subtle；
- border/accent-line；
- accent/foreground-on-accent；
- critical/caution/attested 状态；
- radius、spacing、shadow、motion；
- code background/foreground。

Light/dark 必须分别验证。深色模式的 primary button 不允许出现亮底白字等低对比组合；
interactive states（hover/focus/disabled）必须使用成对 token，而不是只换背景。

UI 原则：

- 简洁，不写用户需要反推含义的文案；
- 一屏一个主要任务；
- typography、card density、radius 和 spacing 全站一致；
- scientific metadata 使用 mono 只限 coordinate、digest、代码和文件名；
- 不把所有内容都装进相同白卡片；用 section、border 和背景层级组织页面；
- mobile 保持阅读顺序，不能只是把 desktop 两栏压成窄列。

## Data and rendering

Web 构建前由 `registry:sync` 将明确 snapshot 放入 `.generated/registry.json`。应用 import
该文件并使用 `@molcrafts/molhub/core` 的 Registry；不在浏览器重新走 artifacts 目录，
也不实现第三套 schema parser。

每个 registry entry 在 production build 中有可直接访问的 prerendered detail HTML。
动态 Inspector bundle 必须 route-level lazy load，不能让 Babylon/MolVis 增加首页与 Explore
的基础 bundle。

## Copy contract

- 产品名统一写 `MolHub`；package/command/path 才使用 `molhub`；
- 主说明使用普通动词 `find / inspect / fetch / submit`；
- CTA 使用具体动作：`Explore datasets`、`Inspect`、`Copy Python`、`Submit manifest`；
- 禁止 `Molecular artifacts.`、`Stable coordinates.` 以及没有解释对象的 `Create`；
- 技术术语第一次出现时必须从用户任务解释，而非用另一个术语定义。

## Accessibility and testing

- 键盘可达、可见 focus、semantic headings；
- icon-only control 有 accessible name；
- kind/state 不能只靠颜色；
- dark/light contrast 自动检查加关键页面人工检查；
- route、snippet、search、submission client 用 Rstest；
- production build 是验收的一部分，不以 dev server 可打开代替。

## Out of scope

- 文档站内容；
- 通用 MolVis 编辑器 UI；
- 社交信息流与排行榜；
- 在首页自动加载 3D canvas。
