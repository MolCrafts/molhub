---
spec: molhub-product-06-docs-operations
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "严格文档构建"
    type: runtime
    pass_when: "Zensical + MolCrafts theme 以 --strict 构建成功，产品标记为 molhub，无坏链接"
    status: passed
    last_checked: 2026-08-09
  - id: ac-002
    summary: "Python 示例可执行"
    type: runtime
    pass_when: "docs 下 Python snippets 全部执行或逐项显式 skip，扩展 Source 示例端到端成功"
    status: passed
    last_checked: 2026-08-09
  - id: ac-003
    summary: "TypeScript 与 REST 示例受测试"
    type: runtime
    pass_when: "TS snippets typecheck，Node snippets smoke，REST snippets 对 contract test server 通过"
    status: passed
    last_checked: 2026-08-09
  - id: ac-004
    summary: "文档不存在已废弃架构"
    type: docs
    pass_when: "自动扫描与人工 review 证明没有 mandatory self-computed sha256、molhub-js/app 独立仓、content-addressed cache 或 website cannot submit 等说法"
    status: passed
    last_checked: 2026-08-09
  - id: ac-005
    summary: "Registry merge 触发可追溯 Web build"
    type: production
    pass_when: "registry merge 生成 snapshot/dispatch，Web 显示包含该 entry 的 build 且能追溯 source commit"
    status: pending
    last_checked: 2026-08-09
  - id: ac-006
    summary: "正式 API 部署与 smoke"
    type: production
    pass_when: "D1/Worker/Secrets 配置完成，health 与 submit/status smoke 通过，并有 rollback/rotation 文档"
    status: pending
    last_checked: 2026-08-09
  - id: ac-007
    summary: "Registry health 不修改数据"
    type: operations
    pass_when: "scheduled job 检查 pinned locator/status/size/digest，失败只报告或开 issue，不向 artifacts 直接写入"
    status: passed
    last_checked: 2026-08-09
  - id: ac-008
    summary: "发布包内容正确"
    type: package
    pass_when: "Python wheel/npm tarball 包含 runtime contract 和 CLI，不含 tests、secrets、dev vars 或 build cache"
    status: passed
    last_checked: 2026-08-09
  - id: ac-009
    summary: "运维日志不泄露隐私与凭据"
    type: security
    pass_when: "自动测试/日志抽检中 contributor email、token、authorization header 和未限长 manifest body 均不存在"
    status: passed
    last_checked: 2026-08-09
out_of_scope:
  - "文档站数据集清单"
  - "自动修复或自动合并 registry"
  - "首版多语言文档"
---

# Acceptance — 文档与运营

Docs 的核心门禁是“例子跑得通且描述当前架构”。漂亮但不可执行的指南，以及自动生成
但没有入口的 API reference，都不算完成。

Production criteria 必须保留部署 URL、workflow run、snapshot commit 与 smoke result
作为证据。`wrangler deploy --dry-run` 和本地 D1 只能满足 implementation gate，不能把
AC-005/006 标为 passed。
