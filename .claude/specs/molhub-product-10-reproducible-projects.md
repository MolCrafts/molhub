---
slug: molhub-product-10-reproducible-projects
status: proposed
created: 2026-08-09
chain: molhub-product
position: 10
depends_on:
  - molhub-product-01-registry-contract
  - molhub-product-02-clients-transport
  - molhub-product-07-live-registry-distribution
scope_layer: project manifests, deterministic lockfiles, multi-artifact sync and citation
lifecycle: durable
---

# Reproducible Projects — 多 Artifact Lockfile、Sync 与 Citation

## Summary

真实实验通常同时依赖 dataset、model、plugin 或同一 dataset 的多个 roles。逐条运行
`molhub fetch` 可以下载文件，却没有一个可提交到 git 的记录说明“这个项目精确使用了
哪些 coordinates、roles 和 registry revision”。

MolHub 增加项目级 declarative intent 与 deterministic lockfile：

```text
molhub.toml     # 人写/CLI 编辑：pinned coordinates + selected roles
molhub.lock     # 机器生成、可读、可提交：manifest evidence + registry revision
```

这不是 Python environment manager、训练 workflow 或新的 artifact identity。Artifact
coordinate 继续是唯一科学制品地址；lockfile 只是一次项目组合的可复现快照。

## CLI workflow

```text
molhub init
molhub add dataset:molcrafts/qm9@v2 --role main
molhub add model:example/mace@1.0 --role weights
molhub remove model:example/mace@1.0
molhub lock
molhub status
molhub sync
molhub verify
molhub cite --format bibtex
```

- `init` 创建最小 `molhub.toml`，不下载；
- `add/remove` 只修改 intent，coordinate 必须含 version；
- `lock` 从当前选定 registry resolution 生成/更新 lockfile，不下载 artifact bytes；
- `sync` 按 lockfile fetch selected roles；
- `verify` 离线检查 cache 中有 published digest/size 的文件；
- `status` 比较 intent、lock、local cache 和当前 registry revision；
- `cite` 从 locked metadata/DOI 导出 citation，不需要重新联网。

没有 public `run_everything` library facade。CLI 组合 project parser、locker、fetcher 和
citation primitives；每个模块可独立单测。

## `molhub.toml` intent

示例：

```toml
schema_version = 1

[[artifacts]]
coordinate = "dataset:molcrafts/qm9@v2"
roles = ["main", "exclude"]

[[artifacts]]
coordinate = "model:example/mace@1.0"
roles = ["weights"]
```

合同：

- coordinate 必须 canonical 且含 version，不允许 version range/`latest`；
- roles 明确列出；缺省 roles 的便利输入在写盘前展开为明确列表，避免未来 manifest 新增
  role 时 `sync` 悄悄多下载；
- duplicate coordinate/role 被规范化或拒绝，输出顺序 deterministic；
- intent 不保存 locator、digest 或 registry URL，这些属于 resolution result；
- 一个项目可以引用 dataset/model/plugin，但不因 kind 自动执行 artifact。

## `molhub.lock` contract

Lockfile 使用 stable-key-order JSON（文件名仍为 `molhub.lock`），至少记录：

```json
{
  "schema_version": 1,
  "registry": {
    "source_revision": "<commit>",
    "schema_version": 1
  },
  "artifacts": [
    {
      "coordinate": "dataset:molcrafts/qm9@v2",
      "title": "QM9 ...",
      "doi": "...",
      "roles": [
        {
          "role": "main",
          "filename": "...",
          "format": "...",
          "size": 123,
          "digest": "md5:...",
          "locators": ["figshare://..."]
        }
      ]
    }
  ]
}
```

- artifact/role/locator order 与 canonical registry contract 一致；
- 不保存临时 signed URL、local absolute path、token 或 contributor data；
- `digest` 只记录 registry 中平台公布的值，缺失时保持缺失；
- 可以计算 lock document/manifest metadata hash 来检测文件被编辑，但必须命名为
  `lock_hash`/`manifest_hash`，不得冒充 artifact digest；
- 同一 intent + 同一 registry revision 生成 byte-identical lock；
- lockfile 单独可用于 sync，不要求 current registry 仍在线；
- locked manifest evidence 与 current registry 同 coordinate 不一致时 hard error，因为
  coordinate immutable；不能静默重写 lock 后继续。

## Resolution and update semantics

`molhub lock` 使用 product-07 当前选定 registry。若 intent 已有 lock：

- 相同 source revision 且 intent 未变：no-op；
- registry revision 变化但 locked coordinates 内容相同：只在显式 `lock --refresh` 时更新
  revision/evidence；
- 同 coordinate 内容变化：报告 registry immutability violation；
- coordinate 不存在：保留旧 lock，指出 missing intent entry；
- 新增/删除 intent entry：生成可审查 diff。

不提供 version range 自动升级。升级 artifact 是用户将 intent 中 coordinate 改为新 version，
随后查看 lock diff。未来可以增加 `versions`/`outdated` 提示，但不能自动改变 scientific
inputs。

## Sync and local layout

`sync` 必须复用 product-02 transport 和共享 cache：

```text
$MOLHUB_HOME/files/<kind>/<namespace>/<name>@<version>/<role>
```

- 先验证整个 lock schema，再开始任何下载；
- bounded concurrency，progress 按 artifact/role 显示；
- 每个 role status → temp → size/digest → atomic rename；
- 一项失败不把半截文件留在最终路径；
- 成功 cache hit 不访问网络；
- `--into` 只 materialize/link/copy 到项目目录，不改变 shared cache identity；
- 文件名冲突使用 coordinate/role 结构化目录，不扁平覆盖；
- offline sync 只接受已有可验证 cache，并汇总 missing roles。

## Citation and provenance export

`cite` 基于 lockfile 输出：

- plain text / BibTeX / CSL-JSON；
- artifact title、version、DOI、coordinate；
- registry source revision；
- 去重同 DOI，但保留多个 coordinate/version 的解释；
- DOI 缺失时使用 manifest 的 upstream link + access statement，不发明 DOI。

未来 Inspector 可以导出一个带当前 coordinate/role/frame 的 project entry，但 frame/plot
selection 仍是 Inspector state，不进入 artifact lock identity。

## Python and TypeScript surfaces

共享语言中立 schema/conformance vectors，至少覆盖 parse、canonical ordering、lock bytes、
drift、sync plan 和 errors。

- Python 暴露小型 `ProjectManifest`、`ProjectLock`、`ProjectLocker` primitives；
- TypeScript `./node` 暴露对应 filesystem/runtime primitives；
- browser root 只暴露 lock schema/types/parse，不暴露 sync/filesystem；
- Python/Node CLI 对同一 fixture 生成 byte-identical lockfile；
- future bindings 可以只实现 parse/verify，不强制实现 filesystem sync。

## Migration and safety

- lock schema 有独立 version，不等于 manifest/registry/package version；
- parser 对未知 breaking version fail loud，并保留原文件；
- migration 是显式命令/备份写入，不原地丢字段；
- `add/remove/lock` 使用 temp + atomic rename，崩溃不截断项目文件；
- 默认不执行 model/plugin、不运行 post-install hooks；
- lockfile 可来自不受信任仓库，因此 paths/filenames 不能逃逸目标目录。

## Delivery phases

### Phase 1 — Contract and deterministic lock

- language-neutral intent/lock schema；
- Python project primitives + CLI init/add/remove/lock/status；
- deterministic and drift fixtures。

### Phase 2 — Sync and verify

- multi-role sync plan；
- shared cache、offline、bounded concurrency、`--into`；
- failure/collision/path traversal tests。

### Phase 3 — Node parity and citation

- Node SDK/CLI parity；
- cross-language byte-identical locks；
- BibTeX/CSL/plain citation；
- docs example from empty directory to offline reproduced cache。

## Out of scope

- Python/npm/conda environment locking；
- training execution、workflow scheduling 或 experiment tracking；
- version ranges 和自动升级 scientific inputs；
- 执行 model/plugin code；
- 在 lockfile 中保存 auth token、signed URL 或本地绝对路径；
- 用自算 artifact digest 改写 manifest semantics。
