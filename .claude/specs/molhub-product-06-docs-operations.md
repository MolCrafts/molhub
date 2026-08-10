---
slug: molhub-product-06-docs-operations
status: in-progress
created: 2026-08-09
last_audited: 2026-08-09
chain: molhub-product
position: 6
depends_on:
  - molhub-product-00-positioning-boundaries
  - molhub-product-01-registry-contract
  - molhub-product-02-clients-transport
  - molhub-product-03-artifact-onboarding
  - molhub-product-05-inspector
scope_layer: docs, releases, deployment and registry operations
lifecycle: durable
---

# 文档、发布与 Registry 运营

## Summary

MolHub 需要三个不同的信息面：

| Surface | URL | 问题 |
|---|---|---|
| Product Web | `app.molcrafts.org/molhub/` | 有什么、如何检查、如何提交 |
| Docs | `docs.molcrafts.org/molhub/` | 如何使用、扩展和运维 |
| Ecosystem landing | `molcrafts.org/molhub/` | MolHub 在 MolCrafts 中是什么 |

Docs 使用 Zensical + `molcrafts-zensical-theme`，与 Python docstrings、TypeScript API
和 specs 同仓。文档站不复制 registry 数据集清单，Web 不承担长篇 SDK 手册。

## Documentation structure

```text
docs/
  index.md
  concepts/
    positioning.md
    coordinates.md
    manifests.md
    integrity-and-cache.md
    repository-boundaries.md
  guides/
    finding-and-fetching.md
    submitting.md
    publishing.md
    extending-sources.md
    using-typescript.md
    migrating.md
  inspector/
    opening-an-artifact.md
    properties-and-selection.md
    derived-data.md
  operations/
    registry-review.md
    deployment.md
    schema-evolution.md
    incident-response.md
  reference/
    python.md
    typescript.md
    rest-api.md
    manifest-schema.md
```

必须修正旧设计遗留的错误说法：

- digest 不是必填 SHA-256，且 MolHub 不自行计算；
- registry 名称不是 index；
- Web/API/TypeScript 不在独立仓；
- 网站可以直接提交 manifest；
- cache 是 coordinate + role，不是 content-addressed blob；
- Inspector 派生数据不是 registry 权威数据。

## Executable documentation

- Python 示例由 pytest 抽取/执行；
- TypeScript 示例在临时 project 中 typecheck，并对 Node 示例做 smoke test；
- REST examples 针对 local Worker 或 contract test server；
- 需要真实网络的示例显式标注，测试输出逐项报告 skipped；
- mkdocstrings/TypeDoc 覆盖公开 API；
- `zensical build --strict` 把坏链接和缺失 anchor 变成失败。

## Release model

各产物独立版本但共享 contract compatibility：

- Python `molhub`；
- npm `@molcrafts/molhub`；
- Web/API deployments；
- registry snapshot revision；
- manifest/registry schema version。

Schema version 不等于 package version。发布说明必须写出：contract 是否变化、registry
snapshot revision、cache/layout 是否变化、需要的 migration，以及 Python/Node 最低兼容
版本。

在发布 npm/PyPI 前运行 pack/wheel content audit，确保 schema、bundled registry 和 CLI
存在，tests、secrets、`.dev.vars`、构建缓存不存在。

## Deployment operations

### Web

- checkout MolHub 与 canonical registry；
- validate/build snapshot；
- test/typecheck/prerender；
- 要求 `MOLHUB_API_URL` 与 Cloudflare Pages project variables；
- deploy immutable build；
- smoke `/molhub/`、Explore、一个 detail、Submit，未来加 Inspector。

### Submission API

- D1 database id 不是仓内 placeholder；
- migrations 先 dry/local，再 remote；
- secrets 通过 Wrangler secrets；
- deploy dry-run 与 Worker integration tests 是门禁；
- smoke health、submit/status；review/webhook 使用专用 staging 流程；
- 文档包含 rollback 和 secret rotation。

### Registry

- PR 运行 canonical validator 和 deterministic builder；
- merge 生成 snapshot artifact，并 dispatch Web rebuild；
- snapshot 带 source commit metadata；
- 不在 registry commit `dist/`；
- production Web 能指出当前 snapshot revision。

## Registry health

定期巡检的目标是尽早发现上游变化，不是自动改 manifest：

- resolve 每个 locator，检查版本仍固定；
- 检查 status、metadata size 和平台公布 digest；
- 对大文件优先使用上游 API/HEAD，避免夜间搬运全 registry；
- 取回失败按 source/coordinate 聚合，减少重复告警；
- 连续失败才创建 issue，临时 429/5xx 使用 bounded retry；
- 任何修复走普通 manifest PR 和 review；
- 记录 last successful check，但运行状态不写回 authored manifest。

完整端到端 byte verification 可以抽样或低频运行，不能把第三方 API 压力变成每天的
默认行为。

## Observability and incidents

至少监测：

- Web build/smoke；
- submission create/error/status transition；
- GitHub publisher 和 webhook signature failures；
- D1 migration/deploy；
- registry build revision；
- locator health by platform；
- Inspector derived job、chunk errors 和 unsupported formats。

日志不包含 contributor email、tokens、完整 authorization headers 或不受限的 manifest
body。Incident guide 必须包含 disable submissions、rotate secrets、rebuild registry、
invalidate derived preview 和 restore previous Web build。

## Local commands

所有命令从 `molhub` root 开始，文档明确 Node 22：

```bash
npm ci
npm run check
npm run dev --workspace @molcrafts/molhub-web
npm run db:migrate:local --workspace @molcrafts/molhub-api
npm run dev --workspace @molcrafts/molhub-api
uv run pytest
```

Registry sibling commands必须使用明确路径，不依赖 npm workspace 改变后的 cwd。

## Out of scope

- 在 docs 手工维护数据集清单；
- 文档站运行用户查询或提交；
- 自动修复/自动 merge locator health failures；
- 第一版国际化。
