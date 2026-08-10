---
spec: molhub-product-05-inspector
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "只有兼容 role 显示 Inspect"
    type: runtime
    pass_when: "shared Inspectability 对每个 artifact 返回 direct/derived/unsupported 和理由；detail page 不靠 filename 条件分支猜测"
    status: passed
    last_checked: 2026-08-09
  - id: ac-002
    summary: "3BPA vertical slice 可用"
    type: e2e
    pass_when: "从 3BPA detail 打开 train_300K，显示结构、frame controls、energy plot 和 provenance"
    status: passed
    last_checked: 2026-08-09
  - id: ac-003
    summary: "Plot 与 viewer 双向联动"
    type: browser
    pass_when: "点击 point 切到对应 frame；scrub/play frame 后 active point 在下一 animation frame 内同步"
    status: passed
    last_checked: 2026-08-09
  - id: ac-004
    summary: "Inspector state 可分享"
    type: e2e
    pass_when: "复制 URL 后在新 context 打开，恢复 coordinate、role、frame、x/y/color；URL 不含临时 source URL"
    status: passed
    last_checked: 2026-08-09
  - id: ac-005
    summary: "Catalog bundle 与 Inspector 隔离"
    type: performance
    pass_when: "home/explore/detail initial chunks 不含 @babylonjs、@molcrafts/molvis-stage 或 @molcrafts/molplot"
    status: passed
    last_checked: 2026-08-09
  - id: ac-006
    summary: "远程操作可取消且不泄漏"
    type: browser
    pass_when: "route change/role change abort 旧 fetch、worker 和 scene；连续切换后只有一个 live engine/runtime"
    status: pending
    last_checked: 2026-08-09
  - id: ac-007
    summary: "Derived data 可追溯且可重建"
    type: data
    pass_when: "descriptor 记录 coordinate、role、source digest/size、converter 和 MolRec schema；删除 derived output 后相同输入生成等价结果"
    status: pending
    last_checked: 2026-08-09
  - id: ac-008
    summary: "Remote MolRec/Zarr 按需读取"
    type: integration
    pass_when: "打开大型 derived dataset 的第一个 frame 不下载完整 record；frame seek 只请求所需 metadata/chunks"
    status: pending
    last_checked: 2026-08-09
  - id: ac-009
    summary: "Atom/environment property 联动"
    type: browser
    pass_when: "atom-level map selection 在 MolVis 居中高亮正确环境，MolVis atom selection 回写属性面板"
    status: pending
    last_checked: 2026-08-09
  - id: ac-010
    summary: "错误状态可操作"
    type: ux
    pass_when: "unsupported、CORS、range unavailable、parse error、corrupt derived data 各有明确原因、retry/fallback 或返回 source 的操作"
    status: pending
    last_checked: 2026-08-09
  - id: ac-011
    summary: "MolHub 不复制 MolVis UI/engine"
    type: architecture
    pass_when: "集成只依赖发布的 MolVis/MolPlot package exports；无 iframe 整页嵌入、无复制 source 文件"
    status: passed
    last_checked: 2026-08-09
  - id: ac-012
    summary: "跨设备与主题可操作"
    type: visual
    pass_when: "desktop/mobile、light/dark、keyboard-only 下完成 role 选择、frame 切换、plot 选择和 share"
    status: pending
    last_checked: 2026-08-09
  - id: ac-013
    summary: "Property map 统一使用 Canvas"
    type: browser
    pass_when: "MolPlot embed options 固定 renderer=canvas；Inspector property map 有可见 canvas、无 SVG；Rsbuild SSR/静态预渲染无 node-canvas 缺失警告"
    status: passed
    last_checked: 2026-08-09
out_of_scope:
  - "Chemiscope 全功能兼容"
  - "浏览器大型 descriptor 训练"
  - "通用 MolVis 编辑器"
---

# Acceptance — MolHub Inspector

## MVP completion gate

Phase 2 只有在 AC-001–006、AC-010–012 全部通过时才叫 3BPA Inspector MVP。一个能
转动分子但没有属性联动、URL 恢复、错误处理或 bundle isolation 的 viewer demo 不算
Inspector。

## Scalable Inspector gate

AC-007–009 是从单个 ExtXYZ demo 进入 Chemiscope 类数据集探索器的门。特别是 AC-008：
如果第一个 frame 仍需要下载完整 QM9/revMD17 派生记录，那么换成 Zarr 只改变了文件名，
没有解决产品问题。

## Visual review matrix

至少保存以下浏览器截图/录像作为审查证据：

- 3BPA frame 0、选中 plot point 后的 frame；
- light/dark desktop；
- narrow mobile 的 viewer/map tabs；
- loading/indexing、unsupported 和 parse error；
- keyboard focus 与 selected point/atom 的非颜色提示。

2026-08-09 本地 Playwright 已验证 3BPA role 切换后只保留一个 viewer，但尚未覆盖 route
change、快速连续 role change 时旧 fetch/worker/scene 的 abort 与 engine/runtime 泄漏，
因此 AC-006 保持 pending。
