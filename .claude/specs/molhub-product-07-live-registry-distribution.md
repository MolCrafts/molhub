---
slug: molhub-product-07-live-registry-distribution
status: proposed
created: 2026-08-09
chain: molhub-product
position: 7
depends_on:
  - molhub-product-01-registry-contract
  - molhub-product-02-clients-transport
  - molhub-product-06-docs-operations
scope_layer: registry distribution, SDK snapshot lifecycle and offline behavior
lifecycle: durable
---

# Live Registry 分发与离线 Snapshot 生命周期

## Summary

合并一份 approved manifest 必须让 Web 和已安装的 Python/Node 客户端都能看到新
coordinate，而不要求发布新的 SDK 版本。与此同时，`Molhub()` 不能为了完成一次本地
`resolve` 隐式访问网络；计算节点必须可以明确、可预测地离线工作。

MolHub 采用“公开静态 snapshot + 显式更新 + 本地原子缓存 + wheel/npm 内置回退”的
模型，不为 registry search 引入数据库服务。

## Product invariant

以下三条必须同时成立：

1. registry 数据更新不要求 Python/npm 发版；
2. 默认 resolve/search 不访问网络；
3. 更新失败不能损坏最后一份可用 snapshot，也不能让 registry 静默变空。

只满足其中两条不算完成。例如默认每次联网读取 CDN 虽然“实时”，但会破坏 HPC/offline
合同；只读 wheel 内置数据虽然离线，却让新增 manifest 实际仍依赖 SDK 发版。

## Public distribution contract

Canonical registry 的发布产物至少提供：

```text
/v1/registry.json
/v1/registry.yaml
/v1/SOURCE_REVISION
/snapshots/<registry-commit>/registry.json
/snapshots/<registry-commit>/registry.yaml
/snapshots/<registry-commit>/SOURCE_REVISION
```

- `/v1/*` 是当前 approved snapshot 的稳定入口，使用 ETag/Last-Modified revalidation；
- `/snapshots/<commit>/*` 是不可变地址，允许长期缓存；
- `SOURCE_REVISION` 是完整 registry git commit，不是构建时间或 SDK version；
- JSON/YAML 必须来自同一次 deterministic build，并继续通过
  `spec/registry.schema.yaml`；
- current alias 更新必须在 immutable snapshot 全部发布成功之后发生；
- CDN 不提供 manifest 写入、查询 API 或“latest coordinate”解析。

Web production build 必须记录它消费的确切 source revision，并链接到 canonical registry
commit。Registry merge dispatch Web rebuild；dispatch 失败应产生可操作告警，不得把
registry publish 本身回滚成未发布。

## Local snapshot store

官方 snapshot 与 artifact bytes 分开存放：

```text
$MOLHUB_HOME/registry/
  current.json
  SOURCE_REVISION
  metadata.json          # source URL, ETag, fetched_at, schema version
  snapshots/<commit>.json
```

它不属于 `$MOLHUB_HOME/files/` 的 artifact cache contract。更新顺序固定为：

1. conditional GET 到临时文件；
2. 限制 response size 并要求成功 HTTP status；
3. 解析 JSON、验证 registry schema 与 coordinate consistency；
4. 验证声明 revision 对应请求的 immutable/current response；
5. 在同一 filesystem 原子替换 `current.json` 与 metadata pointer；
6. 成功后再清理超过保留策略的旧 snapshot。

任何一步失败都保留旧 `current.json`。进程崩溃留下的 temp file 不得在下次启动时被当成
有效 registry。

## Source precedence and offline behavior

Python 和 Node 的规范读取顺序：

1. 调用者显式传入的 registry document/path/URL；
2. `MOLHUB_REGISTRY` / `MOLHUB_REGISTRY_JSON` / `MOLHUB_REGISTRY_URL`；
3. `$MOLHUB_HOME/registry/current.json`；
4. package 内置 snapshot。

`Molhub()`、`resolve` 和 `search` 只走以上本地选择，不触发更新。联网是显式动作：

```text
molhub registry status
molhub registry update
molhub registry update --revision <commit>
molhub registry rollback <commit>
```

Python CLI 和 Node CLI 使用相同动词、source revision 与 observable error code。
`--offline`/`MOLHUB_OFFLINE=1` 禁止所有 registry 和 artifact 网络访问；如果本地没有所需
coordinate，错误应报告当前 revision 与数据来源，而不是建议用户删除 cache。

Browser SDK 继续要求调用者传 document/URL；浏览器没有共享 filesystem，不能伪装成与
Node 相同的 cache。Product Web 继续在 build 时消费明确 snapshot，不在运行时追随 current
alias，以保持预渲染页面与搜索结果一致。

## Freshness and user-facing status

`registry status` 至少显示：

- 当前 source revision；
- 来源是 explicit / cached official / bundled；
- fetched time 与 ETag（若存在）；
- official current revision 是否已知更新；
- schema version；
- entry count。

`status` 默认不联网；`status --check` 才向 current alias 发 conditional request。CLI 不用
“latest artifact”描述 registry freshness，避免与不可省略的 artifact version 混淆。

## Compatibility and migration

- Python 现有目录型 `$MOLHUB_REGISTRY` 继续可用；
- Node 现有显式 JSON path/URL 继续可用；
- package 内置 snapshot 仍用于首次安装与灾难回退；
- registry schema 不兼容时拒绝 promote，并解释需要的最低客户端版本；
- 旧客户端可以继续读取旧 schema 的 immutable snapshot，不要求 current alias 为它动态
  降级；
- metadata cache layout 在稳定版前冻结；以后变更需有 cache schema version/migration。

## Security and operations

- 官方 source URL 必须是 HTTPS；redirect 只允许到配置的 registry origin；
- response 有严格大小上限、timeout 和 bounded retry；
- 不从 snapshot 执行代码，不信任 filename 生成本地路径；
- update 日志只记录 revision、status、size 和错误类型；
- 发布工作流保留 immutable artifact 与 source commit 证据；
- CDN/current alias 故障时，incident runbook 指导固定到已知 revision 并恢复 alias。

## Delivery phases

### Phase 1 — Published read model

- production registry static origin；
- immutable/current URLs、revision 和 cache headers；
- registry merge publish + Web dispatch 的真实 smoke。

### Phase 2 — Python lifecycle

- JSON snapshot reader；
- local store、update/status/rollback；
- bundled fallback、offline 和 corruption tests。

### Phase 3 — Node parity

- Node SDK/CLI 使用相同 precedence 和 store semantics；
- cross-SDK revision/status fixtures；
- browser explicit-source behavior 保持不变。

### Phase 4 — Release integration

- install old SDK → publish new manifest → update registry → resolve new coordinate；
- docs、release notes、incident and rollback evidence。

## Out of scope

- 用 REST/database 替代静态 registry；
- 无版本 coordinate 或自动解析“最新 artifact”；
- 默认在每次 SDK construction 时联网；
- 把 artifact bytes 放进 registry snapshot；
- 自动修改或批准 manifest。
