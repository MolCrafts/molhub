---
slug: molhub-product-02-clients-transport
status: implemented
created: 2026-08-09
last_audited: 2026-08-09
chain: molhub-product
position: 2
depends_on: [molhub-product-01-registry-contract]
scope_layer: Python, TypeScript, CLI, transport and datasets
lifecycle: durable
---

# 多语言客户端、Transport 与 Dataset API

## Summary

Python 和 TypeScript 是同一 MolHub contract 的两个实现，不是两个相似产品。它们必须
共享 coordinate、manifest、registry、digest、cache layout 和 fallback 行为。

## Public surfaces

### Python

`Molhub` 是 resolve/search/fetch 门面：

```python
from molhub import Molhub

hub = Molhub()
manifest = hub.resolve("dataset:molcrafts/qm9@v2")
results = hub.search(query="trajectory", kind="dataset")
paths = hub.fetch("dataset:molcrafts/qm9@v2")
```

`molhub.sources` 提供 `Locator`、`Digest`、`Source`、`PublishingSource`、`Drivers`、
`Fetcher` 和平台 drivers。第三方 Python 包通过 `molhub.sources` entry point 添加
scheme，不修改 MolHub core。

### TypeScript

单一 npm 包 `@molcrafts/molhub` 提供分环境入口：

- root/browser：resolve、search；类型层面不暴露 filesystem fetch；
- `./core`：coordinate、manifest、registry 等纯 contract；
- `./node`：resolve、search、fetch、filesystem cache；
- `molhub-js` CLI：与 Python CLI 使用相同动词。

不建立 `molhub-js` 独立仓。包与 Web/API 放在同一个 monorepo，确保 contract 和消费者
能在同一提交中演进。

### CLI

Python CLI 的规范动词：

```text
molhub search <query>
molhub info <coordinate>
molhub fetch <coordinate> [--into PATH]
molhub cache verify
```

Node CLI 的参数和输出语义保持一致；命令名不同不构成领域语义差异。

## Transport contract

每个 locator 必须依顺序尝试：

1. resolve 为远端文件；
2. 要求成功的 HTTP 状态，`202` 不是下载成功；
3. 流式写入与最终文件相同 filesystem 的临时路径；
4. 检查正整数 size 和可选 platform digest；
5. 失败时清理临时文件并尝试下一个 locator；
6. 全部通过后 atomic rename；
7. 所有 locator 失败时抛出包含逐源原因的稳定错误。

永远不把 0-byte、半截文件、错误响应 body 或 digest mismatch 放进最终 cache path。

## Cache contract

Python 与 Node 共享：

```text
$MOLHUB_HOME/files/<kind>/<namespace>/<name>@<version>/<role>
```

默认根为平台缓存目录下的 `molhub`。缓存键来自 coordinate + role，不依赖 manifest
是否有 digest。缓存命中不访问网络；`cache verify` 对有 digest 的条目重新校验，对没有
digest 的条目报告 skipped 而不是伪造成功。

裸 URL 输入（例如 `CSVDataset("https://…")`）可以保留在 `$MOLHUB_HOME/urls/`，但
它不是跨语言 registry cache contract，文档必须明确区分。

## Conformance

语言中立 vectors 位于 `spec/conformance/vectors/`，覆盖：

- coordinate parse/normalization；
- digest parse/verify；
- cache relative path；
- manifest validation；
- registry resolution/search；
- locator fallback、202、digest mismatch、all-failed、cache-hit。

每种语言写薄 runner。测试向量比较稳定 error code 和 observable behavior，不比较不同
语言的人类错误消息。新增语言绑定必须先通过全部适用 vectors。

## Python dataset layer

`molhub.dataset` 在 transport 上提供科学数据便利层：

- runtime-checkable `MapDataset` / `IterableDataset`；
- `TargetSchema` 区分 graph-level 与 atom-level；
- `Targets(frame)` 是读取/写入 `Frame.meta` 的唯一公共适配；
- `InMemoryDataset` / `SubsetDataset`；
- `QM9Dataset`、`RevMD17Dataset`、`ThreeBPADataset`、`CSVDataset`。

内置 dataset adapter 只持有 coordinate，不重新硬编码上游 URL。它从 `Molhub.fetch`
取得 role→path，再解析成 `molpy.Frame`。`source_id` 可以在 coordinate 后追加 `#` view
qualifier；qualifier 不是新的 artifact coordinate。

## Source drivers

内置 scheme：`https`、`zenodo`、`figshare`、`hf`、`molhub`。平台 driver 负责将自己的
locator 解析为 HTTP 文件，不复制安全下载逻辑。凭据只在确实需要 publish/gated fetch
时读取，匿名 resolve 不因缺 token 失败。

## Compatibility gates

Python 支持 3.12+，并将 pre-1.0 `molcrafts-molpy` 限定在已经验证的小版本区间。MolPy
发布新 minor 后由定期 compatibility job 验证，再通过显式 PR 抬高上界；不允许开放
上界让公开属性重命名静默进入 lockfile。

Python CI 应将 `ty check src/` 设为门禁。MolPy 当前没有 `py.typed`，选择能读取依赖
源码并识别 `Frame` 属性的 checker；tests 中故意非法的 fixtures 不必强行纳入同一门禁。
`Frame.meta` 的 assignment-only 行为仍由 runtime regression test 保护，类型检查不能
替代它。

Alpha 期发生 cache layout 变化时可以选择一次性重新下载，但 release notes 必须明确
说明。进入稳定版后，任何 layout 变化都需要 migration 或显式 cache version。

## Future bindings

新增 Rust/Go/Julia binding 的顺序：

1. 读取 canonical schemas 和 registry snapshot；
2. 实现 coordinate 与错误码；
3. 运行 conformance vectors；
4. 只有在目标环境有安全 filesystem primitive 时实现 fetch/cache；
5. 将语言特有的豁免写进 conformance README。

不要求每种语言都复刻 Python dataset adapters；L1/L2 contract 一致比表面 API 对称更
重要。

## Out of scope

- 浏览器绕过 CORS 任意下载上游；
- 在客户端自动修改 registry；
- 让 digest 变成必填内容地址；
- 强制所有语言拥有相同扩展发现机制。
