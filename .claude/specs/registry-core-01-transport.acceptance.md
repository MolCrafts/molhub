---
spec: registry-core-01-transport
created: 2026-08-06
criteria:
  - id: ac-001
    summary: "非 200 响应不留下任何文件"
    type: runtime
    pass_when: "对返回 HTTP 202 且 body 为空的 URL 调用 fetch，抛出异常，且目标路径与 .part 临时路径均不存在"
    status: verified
    last_checked: 2026-08-06
  - id: ac-002
    summary: "digest 不符即弃并换下一个 locator"
    type: runtime
    pass_when: "两个 locator 中第一个返回内容与声明 sha256 不符时，第一个的字节不落盘，第二个成功且返回其路径"
    status: verified
    last_checked: 2026-08-06
  - id: ac-003
    summary: "传输中断不留半截文件"
    type: runtime
    pass_when: "读取流中途抛 OSError 后，目标路径与 .part 路径均不存在"
    status: verified
    last_checked: 2026-08-06
  - id: ac-004
    summary: "缓存布局与冻结契约逐字一致"
    type: runtime
    pass_when: "digest 为 sha256:abcd… 的制品落盘路径等于 $MOLHUB_HOME/blobs/sha256/ab/abcd…"
    status: verified
    last_checked: 2026-08-06
  - id: ac-005
    summary: "缓存命中不发起网络请求"
    type: runtime
    pass_when: "同一 (locators, digest) 第二次 fetch 时，被替换的 urlopen 桩记录到零次调用，且返回同一路径"
    status: verified
    last_checked: 2026-08-06
  - id: ac-006
    summary: "第三方驱动可经 entry point 扩展"
    type: runtime
    pass_when: "测试内注册一个自定义 scheme 的驱动后，Fetcher 能用该 scheme 的 locator 成功取回，未修改任何 molhub 源文件"
    status: verified
    last_checked: 2026-08-06
  - id: ac-007
    summary: "自建 registry 不被特例化"
    type: code
    pass_when: "fetcher.py 与 driver.py 中不存在对字面量 \"molhub\" 的 scheme 分支判断"
    status: verified
    last_checked: 2026-08-06
  - id: ac-008
    summary: "全部 locator 失败时报告每一个的原因"
    type: runtime
    pass_when: "三个 locator 全失败时抛出的 AllLocatorsFailed 消息中同时含三个 locator 字符串及各自失败原因"
    status: verified
    last_checked: 2026-08-06
  - id: ac-009
    summary: "重复的下载与缓存路径实现被消除"
    type: code
    pass_when: "src/molhub/dataset/ 下不再定义任何 _download 函数，_resolve_cache_path_static 已删除"
    status: failed
    last_checked: 2026-08-06
  - id: ac-010
    summary: "uploader 公开 API 保持可用"
    type: runtime
    pass_when: "现有 tests/test_uploader/ 全部通过且未修改断言，HuggingFaceUploader 与 FigshareUploader 仍可从 molhub.uploader 导入"
    status: verified
    last_checked: 2026-08-06
  - id: ac-011
    summary: "既有数据集行为不回归"
    type: runtime
    pass_when: "tests/test_dataset/ 全部 148 项通过，QM9Source/CSVDataset 的公开签名未变"
    status: verified
    last_checked: 2026-08-06
  - id: ac-012
    summary: "传输层不依赖语义层"
    type: code
    pass_when: "src/molhub/registry/ 下任何文件都不 import molhub.dataset"
    status: verified
    last_checked: 2026-08-06
  - id: ac-013
    summary: "Drivers 是不可变集合"
    type: runtime
    pass_when: "对一个 Drivers 调用 with_driver 后，原对象的 for_scheme 仍拒绝该新 scheme，返回的新对象接受它"
    status: verified
    last_checked: 2026-08-06
out_of_scope:
  - "坐标语法与 manifest 解析（registry-core-02）"
  - "语言中立 conformance 套件（registry-core-03）"
  - "字节内容解析与 Frame 构造"
  - "断点续传与并发分片"
---

# Acceptance — registry-core-01-transport

「完成」= molhub 有了一个**只认字节**的传输层：给它一串 locator 和一个 sha256，
它按序尝试、强制校验、原子落盘到内容寻址缓存；任何失败路径都不在最终位置留下
可被误认为有效缓存的文件。同时，新增一个托管平台只需实现一个协议并注册
entry point，不必改动 molhub 一行既有代码。

验收的重心不在「成功路径能下载」——那是最容易的部分。重心在**五条失败路径**
（ac-001/002/003/008）和**一条反特例化约束**（ac-007）。

## AC-001 — 非 200 响应不留下任何文件

这是本仓真实发生过的事故的直接回归守卫。`https://figshare.com/ndownloader/files/3195404`
实测返回 HTTP 202 + `content-length: 0`，旧实现将其静默写成 0 字节文件并永久缓存，
导致 QM9 排除表为空、3054 个未表征分子混入。

固件：假响应对象 `status=202, body=b""`。断言 `dest` 与 `dest.with_suffix(".part")`
都不存在，且抛出的异常消息含 `HTTP 202`。

## AC-002 — digest 不符即弃并换下一个 locator

digest 不匹配意味着该镜像内容不对，**不重试同一 locator**。
固件：locator A 返回 `b"wrong"`，locator B 返回与声明 sha256 匹配的字节。
断言返回 B 的路径，且 A 的内容从未出现在 `blobs/` 下任何位置。

## AC-003 — 传输中断不留半截文件

固件：假响应的 `read()` 在第一次调用后抛 `OSError`。
断言 `dest` 不存在且 `.part` 已清理（`finally` 分支覆盖）。

## AC-004 — 缓存布局与冻结契约逐字一致

`CLAUDE.md` 把该布局列为「不可随意变更」，因为 TS 客户端要同机共享。
用真实 `tmp_path` 作 `$MOLHUB_HOME`，断言完整路径字符串相等，不做前缀匹配。

## AC-005 — 缓存命中不发起网络请求

把 `urlopen` 替换为调用即失败的桩，第二次 `fetch` 必须完全不触发它。

## AC-006 — 第三方驱动可经 entry point 扩展

这条验证「可扩展」不是口号。测试内定义一个 `scheme = "fake"` 的驱动，通过
测试专用注册路径注入，然后用 `fake://...` 成功取回。**测试期间不得修改
`src/molhub/` 下任何文件**——这正是扩展性的操作性定义。

## AC-007 — 自建 registry 不被特例化

若 `MolHubRegistry` 需要在 `Fetcher` 里开后门，说明 `Registry` 协议抽错了。
静态检查：`fetcher.py`、`driver.py` 的源码文本中不含 `"molhub"` 字面量作为
scheme 比较。这条刻意用最笨的方式实现，因为它的价值在于**难以绕过**。

## AC-008 — 全部 locator 失败时报告每一个的原因

调试多源 fallback 时最痛的是只看到最后一个错。异常消息必须能一次看全。

## AC-009 / AC-010 / AC-011 — 重构不留残骸、不破坏既有面

`_download` 的两份重复实现是本次重构的直接动因之一，必须消失而不是并存。
同时 `molhub.uploader` 与 `molhub.dataset` 的公开签名保持不变——现有 148 项
测试是这条的度量衡，**不允许为让它们通过而修改断言**。

## AC-012 — 传输层不依赖语义层

L1 只认字节。一旦 `molhub/registry/` 出现 `import molhub.dataset`，分层已破，
后续 02–05 的复用假设全部失效。静态 grep 即可判定。
