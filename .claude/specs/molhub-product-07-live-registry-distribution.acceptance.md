---
spec: molhub-product-07-live-registry-distribution
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "Registry current 与 immutable snapshot 正式发布"
    type: production
    pass_when: "production HTTPS origin 提供 v1 current alias、commit-addressed JSON/YAML 和 SOURCE_REVISION；相同输入重复构建 byte-identical"
    status: pending
  - id: ac-002
    summary: "Registry update 是原子的"
    type: runtime
    pass_when: "HTTP failure、截断 JSON、schema error、revision mismatch 和 process interruption 均不替换最后一份可用 current snapshot"
    status: pending
  - id: ac-003
    summary: "默认 SDK 不隐式联网"
    type: runtime
    pass_when: "Python Molhub()、Node Molhub()/CLI 的 resolve/search 在缓存或 bundled snapshot 可用时产生零网络请求"
    status: pending
  - id: ac-004
    summary: "新增 manifest 不要求 SDK 发版"
    type: e2e
    pass_when: "安装已发布 SDK 后再向 registry 合并新 coordinate；执行 registry update 即可 resolve/fetch，期间 Python/npm package version 不变"
    status: pending
  - id: ac-005
    summary: "Python 与 Node 使用相同 revision"
    type: conformance
    pass_when: "两个 CLI 更新同一 official revision 后报告相同 source revision、entry count，并对全部 coordinates/roles 给出相同结果"
    status: pending
  - id: ac-006
    summary: "Offline 与 bundled fallback 可预测"
    type: runtime
    pass_when: "无网络、无 current cache 时使用 bundled；有 current cache 时优先使用它；offline 模式不会发 registry 或 artifact 请求"
    status: pending
  - id: ac-007
    summary: "损坏与不兼容 snapshot 不被静默接受"
    type: security
    pass_when: "超限、非法 schema、重复 coordinate、未知 breaking schema 的 snapshot 均被拒绝并保留旧 revision；registry 不会变成空集合"
    status: pending
  - id: ac-008
    summary: "Registry merge 驱动可追溯 Web refresh"
    type: production
    pass_when: "真实 registry merge 发布 immutable snapshot、更新 current alias、dispatch Web build；页面 footer revision 与 snapshot commit 一致"
    status: pending
out_of_scope:
  - "服务端搜索数据库"
  - "隐式 latest artifact resolution"
  - "SDK construction 自动联网"
---

# Acceptance — Live Registry

核心场景必须使用“旧 SDK + 新 registry entry”验收；如果测试同时重新构建/安装 SDK，便
没有证明 registry 数据与 package release 已解耦。

断网测试不能只 mock update command。需要从一个完全禁止网络的进程创建默认客户端、
resolve cached/bundled coordinate，并确认错误信息能区分“本地没有该 coordinate”和
“registry update 失败”。
