---
spec: molhub-product-00-positioning-boundaries
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "molhub 是产品 monorepo"
    type: code
    pass_when: "Python、TypeScript、Web、API、registry tooling 与 spec 分别位于本规格指定目录"
    status: passed
  - id: ac-002
    summary: "molhub-registry 保持 data-only"
    type: repository
    pass_when: "registry 仓不存在 schema、scripts、package.json、node_modules 或应用源码"
    status: passed
  - id: ac-003
    summary: "首页使用普通语言解释产品"
    type: ux
    pass_when: "首页主标题为 MolHub，紧随一句用户可理解的说明，且不存在 Molecular artifacts 或 Stable coordinates 品牌句"
    status: passed
  - id: ac-004
    summary: "SDK 与 REST API 边界明确"
    type: architecture
    pass_when: "文档明确 REST API 是 contribution control plane，Python/Node SDK 是本地 resolution 和 transport runtime"
    status: passed
  - id: ac-005
    summary: "生态能力不重复实现"
    type: architecture
    pass_when: "MolHub 通过公开包使用 MolVis、MolPlot、MolRec/MolRS，不复制其内部实现"
    status: passed
  - id: ac-006
    summary: "根目录是 Node 操作入口"
    type: docs
    pass_when: "README 给出从 molhub 根目录运行 npm install、Web dev 与 API dev 的准确命令"
    status: passed
out_of_scope:
  - "用户账号与组织权限"
  - "权威科学制品托管"
---

# Acceptance — 产品定位与仓库边界

验收关注的是一项能力“归谁所有”，不只是文件是否存在。新增功能如果同时在 MolHub
和 MolVis 中各写一份，即使测试全部通过也不满足本规格。

`molhub-registry` 的 data-only 检查应由 allowlist 实现，而不是只 ban 当前知道的几个
文件名；否则下一次很容易以另一种工具链文件重新污染数据库仓。
