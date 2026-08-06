---
slug: registry-core-04-ts-client
status: approved
created: 2026-08-06
chain: registry-core
position: 4
depends_on: [registry-core-03-conformance]
scope_layer: cross-repo (molhub-js)
---

# registry-core-04-ts-client — TypeScript 客户端

## Summary

在新仓 `molhub-js` 实现 TypeScript 客户端，覆盖与 Python 端**相同的** L1+L2 能力：
坐标解析、索引读取、多源 fallback、digest 校验、内容寻址缓存。

正确性的唯一定义是 03 的 conformance 向量——**同一批 JSON，两端都必须通过**。

## Domain basis

无物理内容。约束来自运行环境的双重性：

- **Node**：有文件系统，可实现与 Python 完全一致的 `$MOLHUB_HOME` 缓存，同机互相命中。
- **浏览器**：无文件系统、受 CORS 限制、不能任意跨域取字节。因此浏览器构建
  **只支持索引读取与检索**（`resolve` / `search`），不支持 `fetch`。

这不是妥协而是事实：05 的前端只需要浏览与展示，取字节是 Node/CLI 的事。

**序列化格式**：manifest 与索引的权威格式是 YAML（02），但 02 的构建脚本同时
产出 `index.json`。Node 端读 YAML（`yaml` 包，服务端体积不敏感），**浏览器端读
`index.json`**——省掉 30–40 KB gzip 的 YAML 解析器，且 `JSON.parse` 是原生的。
两份产物由同一批 manifest 生成，不存在漂移风险。
两个入口点分开导出，让类型系统在编译期就拦住浏览器里调 `fetch` 的写法。

## Design

### 包结构（npm workspaces，与 molcrafts-index 的 npm 用法一致）

```
molhub-js/
  packages/
    core/          坐标、manifest、索引、digest —— 纯逻辑，零 IO，双环境通用
    node/          FsBlobStore、fetch 驱动、CLI —— 依赖 core
    browser/       仅 resolve/search —— 依赖 core
  apps/
    web/           → registry-core-05
```

`core` 不含任何 IO，这样它能在浏览器、Node、以及 05 的构建期同时使用，
且 conformance 里纯逻辑那部分向量可以只针对 core 跑。

### 与 Python 端的对应

| 概念 | Python | TypeScript |
|---|---|---|
| 坐标 | `Coordinate` | `Coordinate` |
| 驱动协议 | `Registry` Protocol | `Registry` interface |
| 驱动集合 | `Drivers` | `Drivers` |
| 取回器 | `Fetcher` | `Fetcher`（仅 node） |
| 缓存 | `BlobStore` | `FsBlobStore`（仅 node） |
| 入口 | `Molhub` | `Molhub` |

命名刻意保持一致，降低维护两套实现时的心智负担。

### digest 计算

Node 用 `node:crypto` 流式 sha256；`core` 里的纯函数用 Web Crypto
（`crypto.subtle.digest`）以便浏览器也能用。两者必须对同一输入产出同一 hex——
由 03 的 `digest.yaml` 向量守。

### 缓存共享

`FsBlobStore` 必须写出与 Python 端**逐字节相同**的目录布局：

```
$MOLHUB_HOME/blobs/sha256/<前2位>/<完整hex>
```

验收方式是真的跨语言验证（ac-004）：Python 端写入，TS 端读取命中，反之亦然。
这是「同机共享缓存」从口号变成事实的地方。

### 驱动扩展

Python 用 entry point；TS 无对等机制，改为**显式构造**。`Drivers` 与 Python 端同样不可变：

```ts
const hub = new Molhub({ drivers: Drivers.of(new ZenodoRegistry(), new MyRegistry()) })
```

这条差异要写进 03 的豁免清单（ac-007 允许语言特有豁免）。

## 用户侧 API 示例

Node：

```ts
import { Molhub } from "@molcrafts/molhub-node"

const hub = new Molhub()

const info = await hub.resolve("dataset:molcrafts/qm9@v2")
console.log(info.title, info.license, info.targets.graphLevel)

const paths = await hub.fetch("qm9@v2")
// { main: "/Users/x/.cache/molhub/blobs/sha256/ab/abcd…",
//   exclude: "/Users/x/.cache/molhub/blobs/sha256/cd/cdef…" }
```

浏览器（类型系统禁止 `fetch`）：

```ts
import { Molhub } from "@molcrafts/molhub-browser"

const hub = new Molhub({ index: "https://index.molcrafts.org/index.json" })
const results = await hub.search({ kind: "dataset", query: "md17" })
// hub.fetch  ← 编译期报错：Property 'fetch' does not exist
```

CLI（与 Python 端 `molhub` 子命令保持一致的动词）：

```bash
npx @molcrafts/molhub-node search md17
npx @molcrafts/molhub-node info dataset:molcrafts/qm9@v2
npx @molcrafts/molhub-node fetch qm9@v2 --into ./data
```

跨语言共享缓存的实际效果：

```bash
$ molhub fetch qm9@v2                                   # Python 下载
$ npx @molcrafts/molhub-node fetch qm9@v2               # TS 直接命中，零网络
```

## Files

全部在新仓 `molhub-js`：

| 动作 | 路径 |
|---|---|
| new | `packages/core/src/{coordinate,manifest,index,digest,registry}.ts` |
| new | `packages/node/src/{blobs,fetcher,drivers/*,cli}.ts` |
| new | `packages/browser/src/index.ts` |
| new | `packages/*/test/conformance.test.ts` — 消费 03 的向量 |
| new | `.github/workflows/ci.yml` — biome + tsc + vitest + conformance |
| new | 根 `package.json` 的 `workspaces` 字段、各包 `package.json` |

## Tasks

- [ ] Add npm workspaces 骨架 + biome + tsc 严格模式 + vitest
- [ ] Add `core`：`Coordinate` 解析（与 Python 同语法）
- [ ] Add `core`：manifest / index 反序列化，复用 02 的 `manifest.schema.yaml` 做运行时校验
- [ ] Add `core`：`Digest`（Web Crypto，浏览器与 Node 通用）
- [ ] Add `core`：`Registry` interface 与显式注册表
- [ ] Add `node`：`FsBlobStore`，布局与 Python 端逐字一致
- [ ] Add `node`：`Fetcher`，实现与 01 相同的五步 fetch 契约与 fallback 语义
- [ ] Add `node`：https / zenodo / figshare / hf / molhub 五个驱动
- [ ] Add `browser`：仅 resolve/search，类型层面不暴露 fetch
- [ ] Add `node`：CLI，子命令动词与 Python 端一致
- [ ] Add conformance 运行器，消费 03 的固定 ref 向量
- [ ] Add CI：lint + typecheck + unit + conformance 四道门
- [ ] Add 跨语言缓存互通验证（CI 中先跑 Python fetch 再跑 TS fetch，断言零网络）

## Testing

- conformance 向量是主验收手段，单测只补语言特有部分（模块导出、类型边界、CLI 参数解析）。
- 浏览器构建的「不暴露 fetch」用类型测试（`expectTypeOf` 或 `tsd`）验证，
  不是运行时检查——这条约束的价值在编译期。
- 跨语言缓存互通必须在 CI 里真跑，不用 mock：这是 03 的 `cache_layout` 向量
  之外的端到端确认。

## Out of scope

- 前端页面（→ 05；本 spec 只提供它依赖的 `browser` 包）
- Python 端任何改动（若发现两端行为分歧，改的是向量与两端实现，走 03 的流程）
- 字节内容解析、Frame 等价物（TS 端无 molpy，本就不在范围内）
- npm 发布流程与版本策略
