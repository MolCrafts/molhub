---
title: Inspector 生命周期与自动化交互证据
status: approved
created: 2026-08-09
---

# Inspector 生命周期与自动化交互证据

## Summary

扩展 Inspector Playwright 场景，用直接的 fetch signal、Worker、MolVis app/scene/engine 和 trajectory Blob instrumentation，证明快速 role 切换与 route leave 会取消旧工作并释放旧 runtime。另补真实 keyboard-only 操作和 mobile-light screenshot 输入。只有全部直接生命周期断言通过时，product-05 AC-006 才可标记 passed；AC-012 的人工视觉部分继续 pending。

## Design

所有浏览器证据继续放在 `apps/web/e2e/inspector.spec.ts`，复用当前 Inspector route、Playwright helpers 和发布的 `<molvis-viewer>` custom element。生命周期测试使用固定名称 `Inspector lifecycle aborts stale work and disposes resources`，并在 document 脚本运行前通过 `page.addInitScript` 安装 instrumentation。

### Fetch ownership

包装原始 `window.fetch`，读取实际 `Request` 或 `RequestInit` 上的 `AbortSignal`，为 Inspector source request 注册一次性 `abort` listener，并保留 signal 引用。断言直接检查 stale request 的 signal 已进入 `aborted === true` 且 listener 被触发；Playwright 的 `requestfailed` 只能作为辅助证据。

Playwright route 使用硬编码的小型 ExtXYZ fixture，并可延迟指定 role 的 response。场景先让旧 viewer ready，再启动一个 pending role fetch，随后快速切换到最终 role。释放延迟 response 后，旧结果不得覆盖最终 role、frame、metadata 或 URL。

### MolVis lifecycle

instrumentation 包装原始 `customElements.define`。当 incoming name 为 `molvis-viewer` 时，在调用原始 `define` 之前原地 patch incoming constructor prototype 的 lifecycle methods；不得替换 constructor、不得调用第二次 `define`、不得复制 MolVis element。

捕获 `molvis:ready` 时保存真实 `app`、`app.scene` 与 `scene.getEngine()` 引用。对应 element disconnect 后，测试直接断言 `app.isRunning === false`、`scene.isDisposed() === true` 和 `engine.isDisposed === true`。这些引用必须来自 ready event，不能在 dispose 后重新查询 DOM 或以 element 已移除来替代 runtime 断言。

### Worker and Blob ownership

包装原始 `Worker` constructor，记录每个实例的创建 generation，并包装其实例 `terminate`，维护 live worker 集合。切换 role 后，旧 viewer generation 创建的 worker 必须全部 terminated；当前 viewer 可以保留自己的 live workers。离开 Inspector route 后，所有 tracked workers 必须 terminated。

包装 `URL.createObjectURL` / `URL.revokeObjectURL` 时只追踪 `Blob.type === "chemical/x-xyz"` 的 MolHub trajectory Blob。MolPlot、其他图片或第三方 object URL 不进入计数。Canvas 断言只使用 `molvis-viewer canvas`；PropertyPlot Canvas 不属于 viewer/runtime 数量。

### Final states

快速切换稳定后必须满足：URL、role 和 metadata 都属于最终 role；恰好有一个 `<molvis-viewer>` 和一个 `molvis-viewer canvas`；旧 app/scene/engine 已 dispose；旧 generation workers 全部 terminated；只有当前 trajectory Blob URL 仍存活；delayed stale response 不能改变上述状态。

离开 Inspector route 后，viewer 与 viewer canvas 均为零；所有 captured app 停止；所有 captured scene/engine disposed；live tracked workers 和 live trajectory Blob URLs 均为零。

`MolvisPanel` 当前的 fetch abort、Blob revoke 和 subscription cleanup，以及 MolVis element disconnect dispose，均由本 spec 只读验证；本 spec 不修改生产组件。若直接证据失败，按 no-silent-debt 路由独立 debug spec，不在测试证据任务中顺手重写生命周期。

### Keyboard and mobile evidence

Keyboard-only 场景不得调用 locator `.focus()` 或鼠标 API。它使用真实 `Tab` / `Shift+Tab` 导航，以 arrows 操作 select 和 slider，以 `Enter` / `Space` 激活 button/link。每个目标控件必须匹配 `:focus-visible`，且 computed `outline` 或 `box-shadow` 至少一个为非空、非 `none` 的可见值。场景覆盖 artifact role、trajectory frame、Copy link 和 artifact-detail return。

Mobile-light 场景使用 `390 × 844` viewport 与明确 light color scheme，断言关键区域可见且无水平溢出，并附加 screenshot artifact。自动截图不代表 AC-012 的人工视觉审查通过。

### Regression execution

`regressions/molhub-delivery-02-guard-inspector.mjs` 是薄 runner，不包含第二套 browser harness、fixture 或 lifecycle instrumentation。它只以无 shell 参数数组执行：

```text
npm run test:e2e --workspace @molcrafts/molhub-web -- --grep ^Inspector lifecycle aborts stale work and disposes resources$
```

并透传命名 Playwright 测试的退出码。

### Reuse decision

- reuse `waitForViewer`、`viewerState`、`observeFailures` 和 `attachScreenshot` — 扩展现有 Playwright helper。
- reuse `<molvis-viewer>` — patch incoming prototype 后调用原始 `customElements.define`，不替换或重复注册。
- reuse `MolvisPanel` 现有 abort/revoke/subscription cleanup — 以直接证据验证，不修改生产代码。
- reuse MolVis `molvis:ready` app surface — 直接保存并检查 `app.scene` 与 engine lifecycle。
- new — 测试内 fetch、Worker 和 trajectory Blob counters；现有 helper 无法表达这些资源的 ownership。

## Files to create or modify

- `apps/web/e2e/inspector.spec.ts`
- `regressions/molhub-delivery-02-guard-inspector.mjs` (new)

## Tasks

- [ ] Add pre-document fetch-signal, incoming MolVis prototype, ready-reference, Worker, and trajectory-Blob instrumentation to `apps/web/e2e/inspector.spec.ts`
- [ ] Add the named `Inspector lifecycle aborts stale work and disposes resources` Playwright test to `apps/web/e2e/inspector.spec.ts` with delayed fetch, rapid role switching, direct abort and runtime-disposal assertions
- [ ] Add real-keyboard focus traversal and `390 × 844` mobile-light screenshot scenarios to `apps/web/e2e/inspector.spec.ts`, retaining manual AC-012 as pending
- [ ] Add regression example `regressions/molhub-delivery-02-guard-inspector.mjs` as a thin deterministic runner for only the named Playwright lifecycle test
- [ ] Execute `node regressions/molhub-delivery-02-guard-inspector.mjs`
- [ ] Verify the complete Inspector browser suite with `npm run build --workspace @molcrafts/molhub-web` and `npm run test:e2e --workspace @molcrafts/molhub-web -- inspector.spec.ts`
- [ ] Run full check + test suite

## Testing strategy

- `apps/web/e2e/inspector.spec.ts` remains the browser acceptance surface; no duplicate end-to-end suite is placed under Python `tests/`.
- The lifecycle test fulfills hard-coded valid ExtXYZ responses locally, so request timing and expected frames do not depend on external GitHub traffic.
- Fetch cancellation is proven from the exact signal passed to `fetch`, including its abort event and final `aborted` state.
- Runtime disposal is proven from app, scene and engine references captured at `molvis:ready`, not inferred from DOM removal.
- Worker assertions distinguish old and current viewer generations; route leave requires the tracked live set to become empty.
- Blob assertions count only `chemical/x-xyz` object URLs created by MolHub trajectory normalization; canvas assertions count only `molvis-viewer canvas`.
- Stale-result edge cases release a delayed response after the final role is ready and assert that URL, metadata and viewer ownership remain unchanged.
- Keyboard automation uses only `Tab`, arrows, `Enter` and `Space`, and inspects both `:focus-visible` and computed focus styling.
- Mobile-light automation verifies viewport fit and attaches a screenshot for later human review without changing the durable manual criterion.
- Regression example contains no browser logic; `node regressions/molhub-delivery-02-guard-inspector.mjs` succeeds exactly when the named Playwright lifecycle test succeeds。

## Out of scope

- 宣称 product-05 AC-012 的人工 desktop/mobile、light/dark 或 keyboard review 已通过。
- 修改或复制 MolVis/MolRec runtime、custom element 或 Worker 实现。
- Derived descriptor、Zarr、range reader 或 production data plane。
- 把 MolPlot canvas、任意 object URL 或无关 Worker 纳入 viewer lifecycle 计数。
- 以 DOM removal、request failure 或 `app === null` 代替直接 scene/engine/worker disposal 证据。
- 修改 `MolvisPanel` 或其他生产组件。
