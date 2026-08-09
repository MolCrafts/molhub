---
spec: molhub-product-02-clients-transport
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "Python conformance 通过"
    type: runtime
    pass_when: "Python runner 展开并通过全部适用 vectors，runner 元测试能识别故意失败的 case"
    status: passed
    last_checked: 2026-08-09
  - id: ac-002
    summary: "TypeScript conformance 通过"
    type: runtime
    pass_when: "@molcrafts/molhub 对相同 vectors 全绿，不维护第二份测试数据"
    status: passed
    last_checked: 2026-08-09
  - id: ac-003
    summary: "Browser 不暴露 fetch"
    type: types
    pass_when: "browser 入口类型测试证明只能 resolve/search，且 bundle 不引入 node:fs"
    status: passed
    last_checked: 2026-08-09
  - id: ac-004
    summary: "Node 安全取回与 fallback"
    type: runtime
    pass_when: "202、传输中断、digest mismatch 不落最终路径；下一 locator 可成功接管"
    status: passed
    last_checked: 2026-08-09
  - id: ac-005
    summary: "跨 SDK cache layout 相同"
    type: runtime
    pass_when: "Python 与 Node 对同一 coordinate/role 生成完全相同的相对路径并互相命中"
    status: passed
    last_checked: 2026-08-09
  - id: ac-006
    summary: "SDK 可发布"
    type: package
    pass_when: "npm pack --dry-run 只包含 dist、README、package metadata，三个 export 与 CLI 均可加载"
    status: passed
    last_checked: 2026-08-09
  - id: ac-007
    summary: "Dataset adapters 不含上游 URL"
    type: code
    pass_when: "QM9/revMD17/3BPA 通过 coordinate + ArtifactHub 取回，测试 fake 不访问真实网络"
    status: passed
    last_checked: 2026-08-09
  - id: ac-008
    summary: "CLI 动词跨语言一致"
    type: runtime
    pass_when: "Python 与 Node CLI 的 search/info/fetch 对同一 snapshot 给出相同 coordinate 和 role 集合"
    status: passed
    last_checked: 2026-08-09
  - id: ac-009
    summary: "Python 类型检查进入 CI"
    type: code
    pass_when: "CI 对 src/ 执行 ty check，能识别对 molpy Frame 不存在属性的访问"
    status: passed
    last_checked: 2026-08-09
  - id: ac-010
    summary: "MolPy minor compatibility 受控"
    type: operations
    pass_when: "定期 job 测试目标 MolPy 新 minor；失败不抬上界，成功通过显式 PR 更新约束"
    status: passed
    last_checked: 2026-08-09
out_of_scope:
  - "所有语言完全相同的扩展加载机制"
  - "浏览器通用 filesystem cache"
---

# Acceptance — 客户端与 transport

最重要的失败断言是“最终路径不存在”，不能只断言函数抛错。202 事故的根因正是错误
响应虽然没有抛出，但留下了一个会被下一次当作 cache hit 的文件。

跨语言 cache 验收包含真正的双向进程测试：Python 写入后 Node 零网络命中，Node
写入后 Python 零网络命中；路径相同但发生网络访问仍视为失败。
