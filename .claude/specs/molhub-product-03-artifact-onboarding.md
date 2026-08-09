---
slug: molhub-product-03-artifact-onboarding
status: in-progress
created: 2026-08-09
last_audited: 2026-08-09
chain: molhub-product
position: 3
depends_on: [molhub-product-01-registry-contract, molhub-product-02-clients-transport]
scope_layer: publishing, website submission, review and REST API
lifecycle: durable
---

# Artifact 发布、Manifest 提交与审核

## Summary

“把数据放到公共平台”和“把数据登记进 MolHub”是两个连续但不同的动作：

```text
local files ──publish──▶ Zenodo/Figshare/Hugging Face ──returns Locator
                                                        │
hosted artifact + metadata ──submit manifest────────────┘
                                      ↓ review
                             molhub-registry PR
```

已有稳定上游地址的用户直接从 submit 开始。没有托管地址的用户可以先用
`PublishingSource.publish` 上传，再把返回的 locator 填进 manifest。

## Publish bytes

发布与取回属于同一个平台 driver 的两面。可写 driver 实现：

```python
publish(files, target, publication) -> Locator
```

- `Publication` 是冻结值对象，只包含跨平台共同字段；
- `target` 使用平台自己的容器语言，例如 `org/repo`、article id 或 `new`；
- 返回值必须是可直接放进 manifest `locators` 的 pinned `Locator`；
- token 到 publish 调用时才要求；
- Figshare 和 Hugging Face 是首批实现；Zenodo publish 可以在 API 稳定后补充；
- `molhub.uploader` 只作为有明确移除版本的 deprecated shim。

Web 的“one-click upload”不是第一版 submission MVP 的前置条件。浏览器直传大文件涉及
平台 OAuth、断点续传和凭据安全，必须独立设计，不能把长期 token 交给 MolHub Web。

## Submit manifest

两条正式入口进入同一 registry review：

1. **网站**：默认路径。表单实时生成 YAML、复用 canonical validator、允许下载 YAML，
   并直接提交到 API；
2. **GitHub**：高级用户直接向 `molhub-registry/artifacts/...` 提 PR，CI 使用同一 tooling。

网站不能要求用户拥有 GitHub 账号。GitHub 仍是最终审计和合并面，但不是唯一输入 UI。

表单已经支持多 artifacts、每个 artifact 的多 locators，以及逐字段 shared validation
issues；后续向导和 importer 必须继续投影同一个 `ManifestDraft`，不能退回单文件模型。

## Submission REST API

Cloudflare Worker + D1 提供：

| Endpoint | 权限 | 行为 |
|---|---|---|
| `POST /v1/submissions` | public | 校验、阻止 active duplicate、保存 pending |
| `GET /v1/submissions/:id` | public | 返回公开状态，不泄露 contributor email |
| `POST /v1/submissions/:id/review` | admin bearer | approve 或带理由 reject |
| `POST /v1/github/webhook` | GitHub HMAC | merged PR 将 reviewing 置为 accepted |
| `GET /health` | public | liveness |

状态机：

```text
pending ──approve──▶ reviewing ──PR merged──▶ accepted
   └────reject(note)────────────────────────▶ rejected
```

Approve 根据 coordinate 计算 registry path，创建独立 branch、写 manifest、开 PR。若
coordinate 已存在或状态已处理，返回 conflict，不覆盖已有数据。

## Security and privacy

- public manifest request 有严格 body 上限和 streaming read；
- CORS 只允许配置的 Web origin；
- admin token 用 constant-time comparison；
- GitHub webhook 验证 HMAC；
- GitHub API response 有大小上限；
- secrets 只通过 Worker secrets 注入；
- contributor email 不出现在 public status、PR body 或日志；
- public endpoint 在正式上线前必须增加 rate limit 或 Turnstile，但不能把验证码结果当
  manifest 合法性证明。

## Reviewer experience

Web 已有受保护的 review 页面；REST admin endpoint 保持为底层操作面。正式 reviewer
界面展示：

- rendered manifest 与 canonical YAML；
- coordinate/path、DOI、license、locator pinning 与 source reachability；
- duplicate/version warning；
- approve/reject 和必填 review note；
- 已创建 PR 与最终 merge 状态。

Reviewer UI 属于 `apps/web`，认证策略在实现前单独决策；不能因此在 registry 仓加入
后台应用。

## Production readiness

本地实现完成不等于上线完成。完成本 spec 还需要：

- 创建正式 D1 并迁移；
- 设置 GitHub、admin、webhook secrets；
- 配置 webhook 与 `MOLHUB_API_URL`；
- 从 production Web 提交一份测试 manifest，审核后创建 PR，merge 后状态变 accepted；
- 为失败和滥用建立最低限度的日志、告警和恢复说明。

## Out of scope

- MolHub 托管用户原始数据；
- 在浏览器保存上游长期 token；
- 自动批准或自动合并 manifest；
- 将 GitHub 从最终审计链移除。
