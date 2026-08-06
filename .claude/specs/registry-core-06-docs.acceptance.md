---
spec: registry-core-06-docs
created: 2026-08-06
criteria:
  - id: ac-001
    summary: "文档中的每个 Python 代码块都能执行"
    type: runtime
    pass_when: "tests/test_docs_examples.py 抽取 docs/ 下全部 python 代码块并执行，全部通过；被跳过的块在测试输出中逐个列名"
    status: pending
  - id: ac-002
    summary: "严格模式构建通过"
    type: runtime
    pass_when: "uv run zensical build --strict 退出码为 0，无坏内链与缺失 anchor"
    status: pending
  - id: ac-003
    summary: "使用 MolCrafts 主题且产品标记正确"
    type: runtime
    pass_when: "构建产物 HTML 中存在 data-molcrafts-product=\"molhub\""
    status: pending
  - id: ac-004
    summary: "API 参考覆盖全部公开符号"
    type: runtime
    pass_when: "molhub、molhub.registry、molhub.dataset 三个包 __all__ 中的每个名字都出现在 reference 构建产物中"
    status: pending
  - id: ac-005
    summary: "使用 python handler 而非需要 doxygen 的 cpp handler"
    type: code
    pass_when: "zensical.toml 中 mkdocstrings default_handler 为 python，且未声明 cpp handler"
    status: pending
  - id: ac-006
    summary: "docs 依赖与主构建隔离"
    type: code
    pass_when: "zensical 与 molcrafts-zensical-theme 只出现在 [dependency-groups] docs，不在 project.dependencies 或 dev extra"
    status: pending
  - id: ac-007
    summary: "文档不列举具体数据集"
    type: code
    pass_when: "docs/ 下不存在枚举索引内容的数据集清单表，涉及处链接到 05 的应用"
    status: pending
  - id: ac-008
    summary: "扩展指南端到端可跑"
    type: runtime
    pass_when: "docs/guides/extending.md 中的自定义 Registry 示例被执行后，能通过该 scheme 成功取回一个假制品"
    status: pending
  - id: ac-009
    summary: "迁移指南覆盖两次破坏性变更"
    type: docs
    pass_when: "docs/guides/migrating.md 同时说明 QM9Source 等旧 API 到 Molhub 的迁移，以及 molpy 0.12 带来的 frame.metadata 到 Targets 的变更"
    status: pending
  - id: ac-010
    summary: "文档门禁不拖慢主 CI"
    type: code
    pass_when: "文档构建是独立的 CI job，未加入 mol_project.build.check 命令串"
    status: pending
out_of_scope:
  - "registry 浏览应用（registry-core-05）"
  - "molcrafts.org/molhub/ 落地页（molcrafts-index 仓）"
  - "molcrafts-zensical-theme 主题本身的修改"
  - "中文翻译"
  - "C++ API 参考"
---

# Acceptance — registry-core-06-docs

「完成」= 一个没用过 molhub 的人，读完 `docs.molcrafts.org/molhub/` 能自己取到
一个数据集、并知道怎么给它加一个新的 registry 驱动——而且**文档里的每一段代码
都真的跑得通**。

## AC-001 / AC-008 — 可执行文档是唯一有效的防腐手段

文档代码块过期是所有库文档的默认结局。唯一能真正防住的办法是让 CI 执行它们。

因此 ac-001 要求抽取并执行全部 Python 代码块。允许跳过需要真实网络的块，
但**跳过必须在输出中逐个列名**——静默跳过等于没测。

ac-008 单独把扩展指南拎出来，因为「怎么写一个新 Registry」是 01 那套可扩展性
设计对外的唯一门面。如果这段例子跑不通，扩展性就只是 spec 里的说法。

## AC-002 — 严格模式，不是普通构建

`--strict` 把坏内链和缺失 anchor 变成构建失败。文档站的死链和代码里的死引用
同等级别，都该在 CI 拦住。

## AC-003 / AC-005 / AC-006 — 与既有生态一致

主题、产品标记、依赖组三条都照 `molcrafts-zensical-theme` 的既定用法，不发明
新做法。ac-005 特别点出用 `python` handler：主题自带的 `cpp` handler 需要
`doxygen` 在 PATH 上，而 molhub 没有 C++，引入它只会让 CI 无谓变脆。

ac-006 保证文档依赖不污染库的安装面——`pip install molhub` 的用户不该被拖进
一个静态站点生成器。

## AC-004 — 参考文档覆盖全部公开面

用 `__all__` 做机器可判定的覆盖清单。公开了却没文档的符号，要么补文档，要么
它本就不该公开。

## AC-007 — 06 不做 05 的事

一旦文档里出现「molhub 提供以下数据集」的清单，它就会与索引漂移，且没人会记得
更新。数据集清单只有一个真相源：索引。文档链过去。

## AC-009 — 两次破坏性变更都要交代

molhub 短时间内经历了两次会伤到下游的变更：molpy 0.12 让 `frame.metadata` 变成
`Targets(frame)`，以及本链让 `QM9Source` 之类让位给 `Molhub`。迁移指南必须
两件都写——只写新 API 而不写怎么从旧的过来，是把成本转嫁给用户。

## AC-010 — 文档不拖慢主门禁

文档构建要装一整套静态站生成器，比 ruff + pytest 慢一个量级。它该是独立 job，
不进 `mol_project.build.check`，否则每次 `/mol:ship` 都要等它。
