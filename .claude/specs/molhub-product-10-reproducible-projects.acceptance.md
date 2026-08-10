---
spec: molhub-product-10-reproducible-projects
created: 2026-08-09
criteria:
  - id: ac-001
    summary: "Project intent 只接受 pinned coordinates 和明确 roles"
    type: contract
    pass_when: "canonical versioned coordinates/roles 通过；latest、version range、duplicate/unknown role 和隐式 all-future-roles 被稳定拒绝或规范展开"
    status: pending
  - id: ac-002
    summary: "Lockfile 可重复生成"
    type: conformance
    pass_when: "相同 intent + registry revision 在 Python 与 Node 产生 byte-identical stable JSON，artifact/role/locator ordering 固定"
    status: pending
  - id: ac-003
    summary: "Lock evidence 不发明 artifact digest"
    type: data
    pass_when: "lock 只复制 registry published digest/size；metadata hash 名称与 artifact digest 明确区分，缺 digest 的 artifact 仍保持缺失"
    status: pending
  - id: ac-004
    summary: "Lock 可在 registry 离线时 sync"
    type: runtime
    pass_when: "仅凭 lockfile 和 source drivers 可 fetch selected roles；cache hit 的 offline sync 零网络，missing roles 有完整汇总"
    status: pending
  - id: ac-005
    summary: "Multi-artifact sync 保持 transport 安全"
    type: runtime
    pass_when: "bounded concurrent sync 中 202、截断、size/digest mismatch、单 role failure 不留下最终半文件，也不覆盖其他成功 cache entry"
    status: pending
  - id: ac-006
    summary: "Registry drift 被识别而非静默刷新"
    type: integrity
    pass_when: "相同 coordinate manifest evidence 改变时 hard error 并保留旧 lock；revision 改变但内容相同只在显式 refresh 时产生可审查 diff"
    status: pending
  - id: ac-007
    summary: "Citation 离线且可追溯"
    type: runtime
    pass_when: "从 lockfile 离线生成 plain/BibTeX/CSL，包含 coordinate/version/DOI/source revision；无 DOI 时不伪造"
    status: pending
  - id: ac-008
    summary: "不受信任 lockfile 不能逃逸或执行代码"
    type: security
    pass_when: "path traversal、absolute filename、signed URL/token fields、unknown schema 和 plugin/model executable hooks 被拒绝；sync 只写 shared cache/explicit into root"
    status: pending
  - id: ac-009
    summary: "项目文件写入可恢复"
    type: runtime
    pass_when: "init/add/remove/lock/migrate 使用原子写入；process interruption 保留原文件或完整新文件，并有 schema migration backup"
    status: pending
out_of_scope:
  - "环境包管理器"
  - "训练/工作流执行"
  - "自动升级 artifact version"
---

# Acceptance — Reproducible Projects

Cross-language parity 比“两个 parser 都能读”更严格：golden fixture 要比较最终 lock bytes、
sync plan、error code 和 cache relative paths。人类错误文案可以不同。

离线复现的 golden scenario 应从只有 `molhub.toml`、`molhub.lock` 和预热 shared cache 的
空项目目录开始，完全禁网后完成 status、verify、materialize 和 citation。
