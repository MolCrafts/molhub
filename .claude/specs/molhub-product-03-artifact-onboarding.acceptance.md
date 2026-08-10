---
spec: molhub-product-03-artifact-onboarding
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "Website submission 不依赖 GitHub 账号"
    type: runtime
    pass_when: "用户可在 Web 创建合法 manifest、POST 到 API 并收到 submission id 与 pending 状态"
    status: passed
    last_checked: 2026-08-09
  - id: ac-002
    summary: "Website、API、CI 使用同一 validator"
    type: code
    pass_when: "三个入口对相同无效 manifest 返回相同 issue code，不存在手写规则副本"
    status: passed
    last_checked: 2026-08-09
  - id: ac-003
    summary: "审核创建 registry PR"
    type: integration
    pass_when: "approve 创建 coordinate-derived branch/path/PR，状态变 reviewing，已有 coordinate 不被覆盖"
    status: passed
    last_checked: 2026-08-09
  - id: ac-004
    summary: "Merge webhook 完成状态机"
    type: integration
    pass_when: "签名正确的 merged pull_request 将对应 submission 从 reviewing 更新为 accepted；错误签名无副作用"
    status: passed
    last_checked: 2026-08-09
  - id: ac-005
    summary: "公开状态不泄露个人信息"
    type: security
    pass_when: "GET status、PR body 和普通日志均不包含 contributor email"
    status: passed
    last_checked: 2026-08-09
  - id: ac-006
    summary: "生产端到端提交"
    type: production
    pass_when: "从已部署 Web 提交测试 manifest，经真实 review、GitHub PR 和 merge 后状态为 accepted"
    status: pending
    last_checked: 2026-08-09
  - id: ac-007
    summary: "表单支持完整 manifest"
    type: ux
    pass_when: "可以增删多个 artifacts、每个 artifact 的多个 locators，并展示逐字段 shared validation issues"
    status: passed
    last_checked: 2026-08-09
  - id: ac-008
    summary: "公开提交防滥用"
    type: security
    pass_when: "production public POST 具备 rate limiting 或服务端验证的 Turnstile，并保留 body/CORS 限制"
    status: pending
    last_checked: 2026-08-09
  - id: ac-009
    summary: "Reviewer 有正式操作界面"
    type: ux
    pass_when: "受保护 review 页面可查看检查结果并 approve/reject，无需直接调用 REST endpoint"
    status: passed
    last_checked: 2026-08-09
  - id: ac-010
    summary: "PublishingSource 闭环"
    type: runtime
    pass_when: "Figshare/HF fake integration 证明 publish 返回的 Locator 能被同一 driver resolve/fetch"
    status: passed
    last_checked: 2026-08-09
out_of_scope:
  - "自动批准和自动 merge"
  - "浏览器持有上游长期 token"
---

# Acceptance — Artifact onboarding

本地 Workers/D1 测试只证明代码路径存在；ac-006 必须针对真实 deployment、真实 D1 和
真实 registry PR 执行一次。该测试应使用专门的 disposable coordinate，并在测试后通过
新版本或明确的测试 namespace 管理，不能重写已合并 coordinate。

ac-007 的旧缺口已经关闭：表单支持动态增删 artifacts/locators，并把 shared validator 的
逐字段 issues 映射回同一个 `ManifestDraft`。ac-008 仍等待 production public POST 证据；
ac-010 已由 Figshare/HF 的 pinned locator、官方上传响应形状和同 driver
`publish → resolve → fetch` 硬编码回归关闭。
