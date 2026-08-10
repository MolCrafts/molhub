---
slug: molhub-product-09-assisted-onboarding
status: proposed
created: 2026-08-09
chain: molhub-product
position: 9
depends_on:
  - molhub-product-01-registry-contract
  - molhub-product-03-artifact-onboarding
  - molhub-product-07-live-registry-distribution
scope_layer: upstream metadata import, guided manifest authoring and submission drafts
lifecycle: durable
---

# Assisted Onboarding — 从 DOI/Source URL 到可审核 Manifest

## Summary

贡献者不应先学习 locator scheme、平台 API、published digest 和 YAML schema，才能登记一份
已经发布在 Zenodo、Figshare、Hugging Face 或 GitHub 的 artifact。

Assisted Onboarding 允许用户粘贴 DOI 或受支持 source URL，MolHub 读取平台公开 metadata，
生成可编辑 manifest draft，解释无法自动判断的字段，最后仍通过 product-03 的 canonical
validator、submission API 和人工 registry review。

Import 是“有证据的预填”，不是自动批准，也不是把第三方 metadata 当成 MolHub 权威数据。

## Primary user flow

```text
Paste DOI or source URL
  → identify supported platform and exact version
  → fetch bounded public metadata
  → preview identity, files, published checks and evidence
  → user assigns roles/formats/targets and fixes issues
  → canonical validation
  → submit for review
  → status / PR / accepted
```

UI 使用四步向导：

1. **Source** — DOI/URL、平台识别、版本是否固定；
2. **Metadata** — title、description、version、DOI、license 与 evidence；
3. **Files** — 选择文件、role、format/media type、source order；
4. **Review** — human summary、validation issues、YAML advanced view、submit。

熟悉 schema 的用户可以直接进入 `Edit YAML`，但向导和 YAML 必须投影同一个
`ManifestDraft`，不能拥有两套 validation 或互相覆盖未识别字段。

## Supported importers

第一版支持：

- Zenodo record/DOI；
- Figshare article + explicit version；
- Hugging Face dataset/model repository + immutable revision；
- GitHub release/commit-hosted files；
- DOI redirect 到以上受支持 origin。

每个 importer 实现窄接口：

```text
identify(input) → supported | unsupported
inspect(input, abort) → ImportPreview
```

`ImportPreview` 只包含 draft fields、platform evidence、warnings 和 per-field confidence/source。
它不提交、不写 D1、不上传 bytes。平台实现不能伸手修改 Web form 或 canonical validator。

## Version pinning

Importer 必须产出上游理解的固定版本：

- Zenodo 使用具体 record id 与该版本 DOI；
- Figshare 使用 article version，locator 含 `/v<n>/`；
- Hugging Face branch/tag 必须解析为 immutable commit；
- GitHub release/tag 必须解析为 commit-pinned download/raw locator；
- 无法证明固定版本时返回 blocking issue，而不是悄悄使用 `latest/main/master`。

用户可以编辑 importer 输出，但编辑后仍通过同一个 validator。UI 必须说明“版本标签”和
“固定 revision”的区别，不能把成功 HTTP 200 当成 immutable evidence。

## Metadata and file evidence

可自动填充：

- upstream title/description；
- exact version DOI；
- platform license（只有明确字段时）；
- file names、sizes；
- 平台公开的 digest，原算法原值复制；
- version-pinned locators；
- platform/source links。

不得自动声称：

- 一个没有明确 SPDX mapping 的 license；
- 平台未发布的 digest；
- 仅凭扩展名确认复杂 scientific semantics；
- graph/atom targets；
- model training provenance 或 plugin permissions。

Format/media type 可以依据可靠平台 metadata 预填；只有 filename extension 时标为 suggestion，
需要用户确认。MolHub 绝不为了生成 manifest 下载整个 artifact 并自行计算 digest。

## API placement

跨 origin metadata retrieval 属于 submission control plane，在 `apps/api` 暴露：

```text
POST /v1/imports/preview
Content-Type: application/json

{"source":"https://..."}
```

Response 包含 normalized draft、evidence 和 issues，不包含 secrets 或临时 authenticated URL。
该 endpoint 复用 production CORS、body limit、rate limiting/Turnstile policy。Import preview
可以是无状态请求；只有用户正式 submit 后才写 submission record。

若 reviewer 需要核对 importer evidence，submission 可以保存经过大小限制、去除敏感字段的
`import_report`。Manifest 本身仍是唯一进入 registry PR 的 authored document，evidence 不
混入 registry schema。

## SSRF and external API safety

- 只允许明确 importer 识别的 HTTPS origins；
- DOI resolver 的 redirect 每一跳重新检查 allowlist，拒绝 localhost、private/link-local IP；
- 不接受 `file:`, arbitrary port、userinfo 或用户控制的 request headers；
- DNS rebinding/redirect 后 destination 继续受限制；
- response size、redirect count、timeout 和并发有界；
- content type 与 JSON shape 在解析前检查；
- 外部错误被归一为 stable issue code，不把 response body/token 写日志；
- importer 使用匿名 public API；需要 token/gated repo 时明确告知不支持，不向 Web 索要长期
  platform credential。

## Draft lifecycle

未提交 draft 默认保存在浏览器本地，带 draft schema version：

- 自动保存但不包含 reviewer/admin token；
- email 与 manifest draft 分开保存，用户可以选择不持久化；
- schema migration 失败时允许导出原始 YAML，不静默丢弃；
- `Reset` 明确删除本地 draft；
- submit success 后保留 receipt/status link，但不自动重复提交。

未来账号体系可以增加跨设备 drafts，但不是本版前提。Shareable draft 必须显式创建且经过
敏感字段审查，不能把 local draft 自动上传。

## Reviewer experience

Review page 在 existing canonical checks 之外展示：

- importer/platform 与 exact source version；
- 每个自动填充字段的 evidence link；
- 用户修改过的字段；
- HEAD/API reachability、size/digest/pinning checks；
- 无法自动确认的 license/format/targets warnings。

这些信息帮助人工 review，不提高自动批准权限。Approve 仍创建 registry PR，merge 仍由
GitHub webhook 完成 accepted 状态。

## Delivery phases

### Phase 1 — Import contract and one source

- `ImportPreview` type、issue codes、bounded HTTP boundary；
- Zenodo importer；
- Source → Metadata → Files → Review UI；
- canonical validator parity。

### Phase 2 — Platform coverage

- Figshare、Hugging Face、GitHub；
- DOI routing；
- importer-specific fixtures、rate limiting 和 SSRF tests。

### Phase 3 — Draft and review evidence

- local draft persistence/migration；
- sanitized import report；
- reviewer evidence/diff；
- production smoke from source URL to accepted registry entry。

## Out of scope

- 浏览器持有上游长期 token；
- 直接上传大型 artifact bytes；
- 自动批准或自动 merge；
- 任意 URL scraper；
- 下载完整文件来自行计算 digest；
- 自动推断未经平台声明的科学语义。
