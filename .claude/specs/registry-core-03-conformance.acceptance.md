---
spec: registry-core-03-conformance
created: 2026-08-06
criteria:
  - id: ac-001
    summary: "向量文件是纯 YAML，不含任何语言代码"
    type: code
    pass_when: "conformance/vectors/ 下全部文件都是能被通用 YAML 解析器读取的 .yaml，无 .py/.ts/.js"
    status: pending
  - id: ac-002
    summary: "Python 运行器跑通全部向量"
    type: runtime
    pass_when: "uv run pytest tests/conformance/ 全绿，且展开的测试数等于全部向量文件中 case 总数"
    status: pending
  - id: ac-003
    summary: "运行器不是空壳"
    type: runtime
    pass_when: "喂入一份刻意错误的向量时，运行器报告失败而非通过"
    status: pending
  - id: ac-004
    summary: "错误以稳定代码比对而非消息文本"
    type: code
    pass_when: "向量中的 expect.error 全部取自 conformance README 列出的错误码枚举，无任何自然语言消息断言"
    status: pending
  - id: ac-005
    summary: "缓存布局向量断言完整相对路径"
    type: runtime
    pass_when: "cache_layout 向量中每个 case 的 expect_path 是完整相对路径字符串，运行器做相等比较而非前缀匹配"
    status: pending
  - id: ac-006
    summary: "网络调用次数可被断言"
    type: runtime
    pass_when: "mock registry 记录的调用次数与 fallback 向量中 expect.network_calls 一致，包含缓存命中为 0 次的用例"
    status: pending
  - id: ac-007
    summary: "01 与 02 的 runtime 验收项均有向量覆盖或明确豁免"
    type: docs
    pass_when: "conformance README 中的覆盖清单为 01 与 02 每条 runtime criterion 标注了对应向量名或豁免理由，无遗漏项"
    status: pending
  - id: ac-008
    summary: "向量以固定 ref 取用"
    type: code
    pass_when: "CI 中取用 conformance 向量时指定了固定 commit 或 tag，而非索引仓的 HEAD"
    status: pending
  - id: ac-009
    summary: "mock registry 可独立启动"
    type: runtime
    pass_when: "在不导入 molhub 的情况下启动 mock registry 并用 curl 取到剧本中声明的响应"
    status: pending
out_of_scope:
  - "TypeScript 运行器与实现（registry-core-04）"
  - "前端（registry-core-05）"
  - "性能基准"
  - "真实网络集成测试"
---

# Acceptance — registry-core-03-conformance

「完成」= 01 与 02 的跨语言行为不再只存在于 Python 代码里，而是存在于一份
**任何语言都能读、任何实现都必须通过**的 YAML 契约里。

本 spec 不产出用户可见功能。它的全部价值在于：当 04 的 TypeScript 客户端开始
写的时候，「正确」是有定义的，不是靠人对着 Python 源码抄。

## AC-001 / AC-004 — 语言中立是字面意义上的

向量里出现任何一行代码，或任何一条比对人类可读错误消息的断言，本 spec 就失效了：
前者让非 Python 实现无法消费，后者保证两端必然在措辞上漂移。

错误码枚举要在 README 里成文并冻结，`missing_version` 这类名字一旦发布就不改。

## AC-002 / AC-003 — 运行器必须真的在跑

ac-003 是防止「运行器写成了 `pass`」这类空壳的元测试。做法：conftest 提供一份
注入的坏向量，断言运行器对它报失败。没有这条，前面所有绿灯都不可信。

ac-002 额外要求**展开的测试数等于 case 总数**——防止运行器悄悄跳过整个向量文件
（例如某个 YAML 解析失败被吞掉）。

## AC-005 / AC-006 — 两条最容易漂移的行为

缓存布局与网络调用次数，是 Python 与 TS 最可能各行其是的两处，且都不会在功能上
立刻表现为错误——只会表现为「同机两个客户端各下一遍」这种静默浪费。因此必须用
精确相等而非宽松匹配来钉死。

## AC-007 — 覆盖清单，不靠感觉

要求逐条核对 01 与 02 的 runtime criterion。允许豁免（有些确实是语言特有，
例如 entry point 发现机制），但**豁免必须写下来并给理由**，不能沉默地漏掉。
这条是防止 conformance 套件看着热闹、实际只覆盖了简单用例。

## AC-008 — 固定 ref

向量仓与客户端仓分离带来一个新风险：索引仓的一次提交让客户端 CI 突然变红，
而客户端什么都没改。用固定 ref 取用，升级 ref 是一次显式的、可 review 的提交。
