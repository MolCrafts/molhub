---
spec: registry-core-04-ts-client
created: 2026-08-06
criteria:
  - id: ac-001
    summary: "TS 端通过与 Python 端同一批 conformance 向量"
    type: runtime
    pass_when: "molhub-js 的 conformance 运行器对 03 固定 ref 的全部向量通过，且展开用例数与 Python 端相同"
    status: pending
  - id: ac-002
    summary: "浏览器构建在编译期禁止 fetch"
    type: code
    pass_when: "对 browser 包的 Molhub 调用 fetch 的类型测试断言编译失败"
    status: pending
  - id: ac-003
    summary: "缓存布局与 Python 端逐字一致"
    type: runtime
    pass_when: "TS 端写入的 blob 路径字符串与 Python 端对同一 sha256 产出的路径字符串完全相等"
    status: pending
  - id: ac-004
    summary: "跨语言缓存互相命中"
    type: runtime
    pass_when: "CI 中 Python 先 fetch 某坐标，随后 TS fetch 同一坐标时 mock registry 记录到零次网络调用，且两端返回同一路径"
    status: pending
  - id: ac-005
    summary: "digest 计算跨语言一致"
    type: runtime
    pass_when: "digest 向量中每个输入在 Node 与浏览器两种实现下产出的 hex 与向量声明值相同"
    status: pending
  - id: ac-006
    summary: "fetch 五步契约在 TS 端同样成立"
    type: runtime
    pass_when: "TS 端对 HTTP 202、digest 不符、传输中断三种情况均不在最终路径留下文件"
    status: pending
  - id: ac-007
    summary: "core 包零 IO"
    type: code
    pass_when: "packages/core 的源码不 import node:fs、node:http、undici 或任何文件/网络 API"
    status: pending
  - id: ac-008
    summary: "manifest 校验复用 02 的 schema"
    type: code
    pass_when: "TS 端运行时校验加载的是 molhub-index 仓的 manifest.schema.yaml，而非手写的 TS 类型守卫"
    status: pending
  - id: ac-009
    summary: "CLI 动词与 Python 端一致"
    type: runtime
    pass_when: "search / info / fetch 三个子命令在两端接受相同的坐标参数并产出语义相同的输出"
    status: pending
  - id: ac-010
    summary: "四道 CI 门齐备"
    type: runtime
    pass_when: "molhub-js CI 依次运行 biome、tsc --noEmit、vitest、conformance 四步且全绿"
    status: pending
out_of_scope:
  - "前端页面（registry-core-05）"
  - "Python 端改动"
  - "字节内容解析"
  - "npm 发布流程"
---

# Acceptance — registry-core-04-ts-client

「完成」= 存在第二个实现，且它的正确性**不是靠人对着 Python 源码抄出来的**，
而是由 03 的向量判定的。

本 spec 最大的风险不是写不出来，而是写出一个「看起来一样、细节各行其是」的
实现。ac-001/003/004/005 全部指向同一件事：**用机器判定一致性，不用眼睛。**

## AC-001 — 同一批向量，同样的展开数

不仅要全绿，还要**展开用例数与 Python 端相同**。数量对不上意味着某个向量文件
被跳过了——这是最容易发生也最容易被忽略的漂移。

## AC-002 — 浏览器禁 fetch 是编译期约束

浏览器里没有文件系统、且受 CORS 限制，`fetch` 在那里不可能正确实现。与其运行时
抛错，不如让类型系统在写代码的那一刻就拦住。用类型测试验证「这段代码编译不过」，
而不是运行时断言——**这条约束的全部价值在编译期**。

## AC-003 / AC-004 — 共享缓存从口号变成事实

ac-003 是静态的路径字符串相等；ac-004 是端到端的真实互通：Python 下载完，
TS 必须零网络命中。两条都要，因为路径对了不代表读取逻辑对（例如某端多加了一层
子目录，或对已存在 blob 仍重新校验并重下）。

ac-004 在 CI 里真跑，不用 mock 缓存——这是整个跨语言设计里唯一无法用向量覆盖的部分。

## AC-005 — Node 与浏览器两套 crypto 也要一致

TS 端内部就有两个 digest 实现（`node:crypto` 与 Web Crypto）。它们之间的漂移
和跨语言漂移一样致命，因此两套都要过同一批向量。

## AC-006 — 失败路径不是 Python 特有

01 里那三条失败路径（202 / digest 不符 / 中断）是这套设计的核心保证。若 TS 端
只实现了成功路径，用户在两个客户端之间会得到不同的安全等级。

## AC-007 — core 零 IO 是可复用的前提

`core` 要同时服务 Node、浏览器、以及 05 前端的构建期。一旦它 import 了 `node:fs`，
浏览器构建就会带上 polyfill 或直接崩，分包就白做了。静态 grep 判定。

## AC-008 — schema 不许手抄成 TS 类型

手写 TS 类型守卫会立刻与 02 的 schema 漂移，且漂移无人察觉。必须在运行时
加载同一份 `manifest.schema.yaml`。TS 的静态类型可以从 schema 生成，但**校验的真相源
只有一个**。
