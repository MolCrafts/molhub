---
spec: molhub-product-01-registry-contract
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "唯一手写 schema"
    type: code
    pass_when: "contract:check 证明所有 Python/TypeScript schema 与 validator 都由 spec/ 生成且无漂移"
    status: passed
    last_checked: 2026-08-09
  - id: ac-002
    summary: "静态 validator 可在 Node ESM、browser 与 Worker 运行"
    type: runtime
    pass_when: "生成代码不含 eval、new Function 或 require，并在三种目标构建/测试中通过"
    status: passed
    last_checked: 2026-08-09
  - id: ac-003
    summary: "非法 manifest 被统一拒绝"
    type: runtime
    pass_when: "缺 version、移动 locator、无 digest/size、size 0、path mismatch、duplicate role 等 fixtures 均被拒绝且理由正确"
    status: passed
    last_checked: 2026-08-09
  - id: ac-004
    summary: "真实 registry 可重复构建"
    type: runtime
    pass_when: "连续两次从同一 artifacts 目录构建的 JSON/YAML 分别 byte-identical"
    status: passed
    last_checked: 2026-08-09
  - id: ac-005
    summary: "聚合 registry 自验证"
    type: runtime
    pass_when: "builder 输出在写盘前通过 registry.schema.yaml，coordinate 字段与四个身份字段逐项一致"
    status: passed
    last_checked: 2026-08-09
  - id: ac-006
    summary: "版本演化受控"
    type: process
    pass_when: "任何破坏性 schema 变更同时提升 schema_version、更新 vectors、Python 与 TypeScript consumers"
    status: pending
    last_checked: 2026-08-09
  - id: ac-007
    summary: "Inspector 元数据不污染 registry"
    type: architecture
    pass_when: "registry 只保存字节语义；preview、相机、图表轴和布局均在派生数据或 URL state 中"
    status: passed
    last_checked: 2026-08-09
out_of_scope:
  - "科学文件解析"
  - "排行榜和下载统计"
---

# Acceptance — Registry contract

Schema 校验只是第一层。固定版本 locator、路径一致性、重复 role 和 DOI 等需要可操作
错误消息的领域规则必须继续由共享 `ManifestValidator` 处理，并在 Web、API 与 CI 中保持
相同 issue code。

可重复构建要比较输出字节或 cryptographic hash，不能只比较反序列化后的对象。
