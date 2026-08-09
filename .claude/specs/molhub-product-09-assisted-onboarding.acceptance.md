---
spec: molhub-product-09-assisted-onboarding
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "用户可从 source URL 开始而非空白 schema"
    type: ux
    pass_when: "粘贴支持的 Zenodo/Figshare/HF/GitHub URL 后得到可编辑 draft、files、evidence 和逐字段 issues，并能完成四步 review/submit"
    status: pending
  - id: ac-002
    summary: "Importer 只生成固定版本 locator"
    type: contract
    pass_when: "Zenodo record、Figshare version、HF commit、GitHub commit fixtures 通过；latest/main/master、未定版本 article 和移动 redirect 被 blocking issue 拒绝"
    status: pending
  - id: ac-003
    summary: "平台 metadata 不被夸大"
    type: data
    pass_when: "digest 只复制平台公开值，license/format suggestion 标记 evidence/confidence，targets/training provenance 不从 filename 猜测"
    status: pending
  - id: ac-004
    summary: "Importer 与手工表单共用 canonical validator"
    type: architecture
    pass_when: "imported、wizard-edited、YAML-edited 和 API-submitted manifest 对相同错误产生相同 shared issue code，无 importer 专属 schema fork"
    status: pending
  - id: ac-005
    summary: "Import endpoint 抵抗 SSRF 与资源滥用"
    type: security
    pass_when: "private/link-local destination、DNS/redirect escape、arbitrary port、oversized/slow response、bad content type 和 unsupported origin 均被有界拒绝且日志无 response body/secrets"
    status: pending
  - id: ac-006
    summary: "Draft 可恢复且可迁移"
    type: browser
    pass_when: "刷新恢复当前 step 与 manifest；reset 删除；draft schema 升级可迁移或导出原 YAML；email/token 不进入非预期持久化"
    status: pending
  - id: ac-007
    summary: "Reviewer 看得到 import evidence"
    type: ux
    pass_when: "review page 展示 source version、field evidence、用户修改和 reachability/pinning checks；approve 权限与状态机未扩大"
    status: pending
  - id: ac-008
    summary: "真实 URL 到 accepted registry entry 闭环"
    type: production
    pass_when: "从 production Web 导入一个 disposable public record，提交、review、PR、merge 后 accepted；manifest 中无 import report 或临时 URL"
    status: pending
out_of_scope:
  - "大型文件浏览器上传"
  - "自动审批"
  - "任意 URL 抓取"
---

# Acceptance — Assisted Onboarding

平台 happy-path fixture 不足以证明 importer 安全。每个 importer 都必须覆盖移动版本、API
返回不完整、公开 digest 缺失、rate limit、redirect 和 abort；失败 draft 不得残留一半
被 UI 标为 Ready。

Production smoke 应使用可清理/可识别的测试 namespace，但一旦 coordinate 合并便保持
immutable；清理通过后续版本或 registry policy，而不是重写历史 manifest。
