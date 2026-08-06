---
spec: registry-core-02-coordinate-index
created: 2026-08-06
criteria:
  - id: ac-001
    summary: "坐标全称与简写解析一致"
    type: runtime
    pass_when: "qm9@v2 与 dataset:molcrafts/qm9@v2 解析为同一 Coordinate，且规范化字符串相等"
    status: pending
  - id: ac-002
    summary: "缺版本的坐标被拒绝"
    type: runtime
    pass_when: "解析 dataset:molcrafts/qm9 抛出错误，消息指出缺少 @version"
    status: pending
  - id: ac-003
    summary: "无 sha256 的 manifest 无法加载"
    type: runtime
    pass_when: "加载一份 artifacts[0] 缺 sha256 的 manifest fixture 时抛出校验错误"
    status: pending
  - id: ac-004
    summary: "索引 CI 拒绝无 digest 的条目"
    type: runtime
    pass_when: "molhub-index 的 validate 工作流对缺 sha256 的 manifest PR 返回非零退出码"
    status: pending
  - id: ac-005
    summary: "新增数据集不需要改 molhub 源码"
    type: runtime
    pass_when: "向 $MOLHUB_INDEX 目录新增一个 manifest 文件后，Molhub().resolve 与 Molhub().fetch 能处理该坐标，且 src/molhub/ 未被修改"
    status: pending
  - id: ac-006
    summary: "fetch 按 role 返回全部制品路径"
    type: runtime
    pass_when: "对含 main 与 exclude 两个 artifact 的 manifest 调用 Molhub().fetch，返回字典含且仅含这两个 role 键，值均为已存在的文件路径"
    status: pending
  - id: ac-007
    summary: "manifest 的 digest 被传递到传输层"
    type: runtime
    pass_when: "假驱动返回与 manifest sha256 不符的字节时，Molhub().fetch 抛错且不落盘"
    status: pending
  - id: ac-008
    summary: "硬编码上游 URL 已从源码消失"
    type: code
    pass_when: "src/molhub/dataset/ 下不存在 _DEFAULT_URL、_EXCLUDE_URL、BASE_URL 常量，且无 figshare.com / ndownloader 字面量"
    status: pending
  - id: ac-009
    summary: "既有数据源公开签名不变且行为一致"
    type: runtime
    pass_when: "QM9Source(root)、CSVDataset(path)、ThreeBPASource(path, tag=)、RevMD17Source(root, molecule=) 构造签名未变，且用合成 fixture 得到的样本数与目标值与迁移前逐位相同"
    status: pending
  - id: ac-010
    summary: "source_id 返回规范坐标"
    type: runtime
    pass_when: "迁移后 QM9Source(...).source_id 是一个能被 Coordinate 成功解析的字符串"
    status: pending
  - id: ac-011
    summary: "离线可用"
    type: runtime
    pass_when: "设置 $MOLHUB_INDEX 指向本地目录并预置缓存后，整个测试套件在断网环境下通过"
    status: pending
  - id: ac-012
    summary: "typer CLI 四个子命令可用"
    type: runtime
    pass_when: "typer CliRunner 调用 search / info / fetch / cache verify 四个子命令在本地索引下均退出码为 0 并产出非空输出"
    status: pending
  - id: ac-013
    summary: "构建同时产出 index.yaml 与 index.json"
    type: runtime
    pass_when: "build_index 运行后 dist/index.yaml 与 dist/index.json 均存在，且解析后内容等价"
    status: pending
  - id: ac-014
    summary: "manifest 支持注释且注释不影响解析"
    type: runtime
    pass_when: "带 # 注释的 manifest YAML 加载成功，且得到的 Manifest 与去掉注释的同一文件相等"
    status: pending
  - id: ac-015
    summary: "schema 可被非 Python 消费者独立校验"
    type: docs
    pass_when: "manifest.schema.yaml 是自包含的 JSON Schema（以 YAML 书写），用任一通用校验器对示例 manifest YAML 校验通过，不依赖 molhub 代码"
    status: pending
out_of_scope:
  - "字节内容解析与 Frame 构造（L3）"
  - "TypeScript 客户端（registry-core-04）"
  - "conformance 测试向量（registry-core-03）"
  - "索引服务端 API、账号、下载量统计"
---

# Acceptance — registry-core-02-coordinate-index

「完成」= 一个数据集的**身份**（坐标）与它的**位置**（locator）彻底分开，
且位置写在一份可被外部 PR 修改的 YAML 里而不是 Python 常量里。

判断本 spec 是否真的达成目标，只需问一个问题：**新增一个数据集，需要发布
molhub 新版本吗？** 答案必须是「不需要」——这就是 ac-005。

## AC-001 / AC-002 — 坐标语法

简写存在的意义是日常好用，全称存在的意义是无歧义；两者必须解析到同一对象，
否则简写就是第二套语法。缺版本必须硬拒——放行会让「可复现」失去意义，且日后
再收紧就是破坏性变更。

## AC-003 / AC-004 — digest 必填是硬门禁，不是建议

这条直接来自本仓的真实事故：链接没坏，返回了 202，而客户端因为没有 digest
可校验，照单全收。放行一个无 digest 的 manifest 等于把那个坑重新挖开。

两处都要拦：客户端加载时拒绝（ac-003），索引 CI 合入时拒绝（ac-004）。
只有后者才真正防住——但前者保证即使索引被绕过，客户端也不会盲信。

## AC-005 — 新增数据集不需要改 molhub 源码

**本 spec 的中心断言。** 测试流程：把一份新 manifest 写进 `$MOLHUB_INDEX` 指向的
临时目录，然后 resolve + fetch 该坐标。断言全程 `src/molhub/` 未被写入
（用文件 mtime 或 git 状态判定）。

这条若不成立，整个「manifest 而非代码」的设计就没有兑现，02 应当推倒重来。

## AC-006 / AC-007 — Molhub 是 01 的组合者，不是重新实现

`Molhub.fetch` 不得自己发 HTTP。ac-007 通过让 mock 驱动返回错字节来证明 digest
确实一路传到了 01 的校验逻辑——如果 `Molhub` 私自跳过校验，这条会失败。

## AC-008 / AC-009 / AC-010 — 迁移彻底且不伤既有用户

ac-008 用 grep 保证硬编码 URL 真的消失而不是被注释掉。ac-009 是不回归的度量衡：
构造签名不变，且**用同一份合成 fixture 得到的样本数与目标值逐位相同**——
不允许「大致一样」。

## AC-011 — 离线可用

科研环境常在无外网的集群上跑。索引可从本地目录加载、缓存命中不联网，这两条
合起来必须让整个套件断网可跑。这也是 CI 的隐含要求：测试不该依赖 Zenodo 的可用性。

## AC-013 — schema 是给别人用的

manifest schema 的消费者包括未来的 TS 客户端、前端、以及任何第三方工具。
它必须能被一个通用 JSON Schema 校验器独立使用，不含任何只有 Python 才懂的约定。
这条是 03 与 04 能否落地的前提。
