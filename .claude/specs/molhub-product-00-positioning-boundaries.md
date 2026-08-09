---
slug: molhub-product-00-positioning-boundaries
status: implemented
created: 2026-08-09
chain: molhub-product
position: 0
depends_on: []
scope_layer: product and repository topology
lifecycle: durable
---

# MolHub 产品定位与仓库边界

## Summary

MolHub 是 MolCrafts 生态的制品目录和入口。它让用户用一个带版本的名字发现、检查并
取回 molecular datasets、models 和 plugins，也让贡献者在不理解 GitHub 工作流的
情况下提交新 manifest。

面对用户的第一层文案必须是普通语言：

> **MolHub**
>
> Find, inspect, and fetch versioned molecular datasets, models, and plugins.

不要再使用用户无法直接解释的品牌句，例如 “Molecular artifacts. Stable
coordinates.”。坐标、manifest、digest 是产品实现，不是首页要求用户先学习的概念。

## Product boundary

MolHub 负责：

- 版本化坐标和 manifest 契约；
- registry 浏览、搜索和详情页；
- Python / TypeScript / CLI 的解析与取回；
- 从网站或 GitHub 提交 manifest，并进入同一审核流程；
- 用 MolVis 检查 registry 中可以解释的科学内容；
- 将上传发布到外部公共数据平台，并返回可写入 manifest 的 locator。

MolHub 不负责：

- 成为通用对象存储或复制所有科学原始数据；
- 重新定义分子结构、trajectory 和 observable 的语义——这是 MolRec；
- 自己实现分子渲染——这是 MolVis；
- 承担实验运行、任务队列或模型训练——分别属于 Molexp、MolQ、MolNex；
- 用一个 REST API 取代所有本地 SDK。

权威科学字节继续留在 Zenodo、Figshare、Hugging Face、git host 等上游。Inspector
使用的派生索引、采样和 preview 可以存入 MolHub 管理的静态存储或 R2，但它们必须
标记为可重新生成，不能冒充权威原始制品。

## Repository topology

`molhub` 是产品 monorepo：

| 路径 | 所有权 |
|---|---|
| `src/molhub/` | Python SDK、CLI、dataset adapters |
| `packages/typescript/` | `@molcrafts/molhub` browser/core/node SDK 与 CLI |
| `packages/registry-tools/` | manifest 校验和 deterministic snapshot builder |
| `apps/web/` | 面向用户的 TanStack Start 应用 |
| `apps/api/` | manifest submission/review Cloudflare Worker |
| `spec/` | 唯一手写 schema 和跨语言 conformance vectors |
| `docs/` | 使用手册与 API reference |

`apps/` 的含义是“可独立部署的运行单元”，不是“所有前端”。当前有 Web 和 API；只有
出现独立部署、独立运行时或独立权限边界的产品，才增加新的 app。普通页面、后台审核
页面或 Inspector 都属于 `apps/web`，不能因为页面变大就另开仓。

`molhub-registry` 是 data-only repository，只允许：

```text
artifacts/<kind>/<namespace>/<name>/<version>.yaml
.github/workflows/
README.md
CLAUDE.md
.gitignore
```

它不拥有 schema、validator、builder、Node/Python 包、Web 或 REST API。`dist/` 是 CI
生成的 disposable output，不提交。

## API boundaries

“Python API”和“REST API”不是同一层：

- Python API 在用户进程内解析、搜索、取回、缓存并适配成 `molpy.Frame`；
- TypeScript browser API 只解析和搜索；Node API 还负责取回与本地缓存；
- REST API 当前是 contribution control plane：提交、状态、审核、GitHub webhook；
- registry snapshot 是静态数据面，不需要为搜索强行增加服务端；
- Inspector 的大文件访问可以增加独立 data-plane endpoint，但不能塞进 submission API
  的领域服务中。

未来 Go、Rust、Julia 等语言绑定必须从 `spec/` 和 conformance vectors 开始，不能从
Python 类逐行翻译并重新发明行为。

## Ecosystem contract

| 项目 | 在 Inspector/Registry 流程中的角色 |
|---|---|
| MolHub | coordinate、provenance、发现、贡献、Inspector host |
| MolVis | 2D/3D viewer、trajectory、选择、分析、RPC |
| MolPlot | linked plots 和科学图表 |
| MolRec | structures、trajectory、observables 的语义合同 |
| MolRS | native/WASM parser 和 compute kernels |
| MolPy | Python 数据模型与 workflow 接口 |

跨仓能力必须沿这条边界实现。MolHub 不复制 MolVis 组件，MolVis 不读取 MolHub
registry，MolRec 不拥有任何产品页面。

## Quality rules

- 所有 Node workspaces 使用根 `package-lock.json` 和 Node 22 LTS；
- 产品代码、契约与生成器同一次变更提交，registry 数据更新不要求 SDK 发版；
- 任何生成副本必须有 drift check；
- README、Web 文案与 specs 对产品定位只能有一个解释；
- 已实现的 durable product spec 不在 implementation 完成后删除，而是更新状态和变更
  记录。

## Out of scope

- 统一登录与组织账号；
- 下载量、评分、评论或社交功能；
- 权威科学数据的长期托管；
- 用 MolHub 替换每个外部数据 repository。
