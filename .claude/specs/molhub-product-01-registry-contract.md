---
slug: molhub-product-01-registry-contract
status: implemented
created: 2026-08-09
last_audited: 2026-08-09
chain: molhub-product
position: 1
depends_on: [molhub-product-00-positioning-boundaries]
scope_layer: coordinate, manifest, registry
lifecycle: durable
---

# Coordinate、Manifest 与 Registry 契约

## Summary

数据集不是 SDK 代码，而是一份经过审核的 manifest。新增或发布一个 artifact 不要求
MolHub SDK 发版；客户端通过稳定 coordinate 解析 registry snapshot。

唯一规范坐标是：

```text
<kind>:<namespace>/<name>@<version>
dataset:molcrafts/qm9@v2
model:molcrafts/mace-mp-0@1.0
plugin:molcrafts/molvis-render@0.3.1
```

版本不可省略。Python/TypeScript CLI 可以接受 `qm9@v2` 作为默认
`dataset:molcrafts` 的输入便利，但存储、URL、输出和代码片段都使用 canonical 全称。

## Source of truth

以下两个文件是唯一手写 schema：

- `spec/manifest.schema.yaml`：贡献者写的一份 manifest；
- `spec/registry.schema.yaml`：builder 生成的聚合 snapshot。

`scripts/sync-contract.ts` 单向生成：

- Python wheel 内的 schema bundle；
- TypeScript schema constants；
- 不包含 `eval` / `new Function` / CommonJS `require` 的静态 validator。

`contract:check` 必须在 CI 中阻止任何生成副本漂移。Web、API 和 registry tooling
直接复用 TypeScript `ManifestValidator`，不能实现“差不多一样”的表单规则。

## Manifest semantics

Manifest v1 的核心字段：

- `kind / namespace / name / version`：组成 immutable coordinate；
- `title / description / license / doi`：发现与 provenance；
- `artifacts[]`：role、filename、有序 locators、可选 digest/size；
- `targets`：graph-level 与 atom-level 名称声明。

硬规则：

1. coordinate 对应的文件路径必须与 manifest 内身份一致；
2. 已发布 coordinate 不原地改成另一批字节，新版本写新文件；
3. locator 必须钉住上游理解的版本：Figshare `/v<n>`、Hugging Face commit、git
   commit，不允许 `main`、`master` 或“latest”；
4. DOI 记录确切发布版本；确实没有 DOI 的来源需要显式的可解释豁免流程，不能静默空值；
5. 每个 artifact 至少有平台公布的 digest 或正整数 size；
6. MolHub 不为 cataloguing 自行下载整个制品并发明 digest；
7. locator 顺序是 fallback 优先级，builder 和客户端不得重排；
8. `targets` 是描述性信息，transport 不据此猜测文件内容。

Digest 是上游不变性的交叉检查，不是 coordinate，也不是 MolHub 自己签发的身份。
`size: 0` 永远非法，因为它正是失败响应被错误落盘的形状。

## Registry build

数据仓路径：

```text
molhub-registry/artifacts/<kind>/<namespace>/<name>/<version>.yaml
```

`packages/registry-tools` 完成：

- schema 与领域规则验证；
- path-coordinate 一致性、duplicate coordinate/role、固定版本 locator 检查；
- 按 coordinate 和 role 的 deterministic ordering；
- 同时生成 `dist/registry.json` 与 `dist/registry.yaml`；
- 对生成结果再次用 registry schema 验证；
- unchanged input 产生 byte-identical output。

Web 构建只消费一个明确 snapshot；Python wheel 可携带发布时的离线 snapshot。Registry
仓不复制工具链，而是在 CI checkout `molhub` 后运行它。

## Contract evolution

一旦 registry 对外接受贡献，任何破坏性收紧必须提升 `schema_version`。可选字段也必须
先进入 canonical schema 和 conformance vectors，随后才生成各语言副本。

Inspector 可能需要 artifact 的 `format` 或 `media_type`。这类字段描述字节，可以进入
manifest；面板布局、颜色、相机和 scatter axis 属于 UI state，不得进入 registry。
生成的 preview/index 也不得作为人工编写的 manifest 内容混入数据仓。

## Search contract

Search 至少支持：

- free-text 对 title、description、coordinate、role、filename、targets；
- kind filter；
- deterministic registry order；
- exact coordinate resolution；
- 不存在的 coordinate 返回稳定错误类型，而不是空 manifest。

## Out of scope

- 字节格式解析；
- Inspector 的视觉状态；
- 下载次数与流行度排序；
- 自动修改已审核 manifest。
