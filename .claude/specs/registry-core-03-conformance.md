---
slug: registry-core-03-conformance
status: approved
created: 2026-08-06
chain: registry-core
position: 3
depends_on: [registry-core-01-transport, registry-core-02-coordinate-index]
scope_layer: cross-language contract
---

# registry-core-03-conformance — 语言中立一致性套件

## Summary

把 01 与 02 里「藏在 Python 实现中」的行为，提取为一套**语言中立的测试向量 +
一个 mock registry 服务**，并让 Python 客户端作为**第一个通过者**。

这是整条链里唯一一个不新增用户可见功能、却决定项目能否长期维护的 spec。
它存在的理由：**Python 与 TypeScript 两套实现必然漂移，而 code review 兜不住。**

## Domain basis

无物理内容。设计依据是本次讨论确立的判断：多语言绑定是本设计最大的可维护性风险，
须以「规格先行」应对。参考先例：CommonMark spec 的 `spec.txt`、WebAssembly 的
`testsuite` 仓、JSON Schema 的 `JSON-Schema-Test-Suite` —— 三者都用同一模式解决了
「N 个实现如何不漂移」。

## Design

### 向量格式

纯 **YAML**，每个文件一组同类用例。**不含任何语言的代码。**

`vectors/coordinate.yaml`：

```yaml
description: Coordinate parsing and normalisation
cases:
  - name: shorthand expands to defaults
    input: qm9@v2
    expect:
      kind: dataset
      namespace: molcrafts
      name: qm9
      version: v2
      canonical: dataset:molcrafts/qm9@v2

  - name: missing version is rejected
    input: dataset:molcrafts/qm9
    expect:
      error: missing_version        # 稳定错误码，不比对人类可读消息
```

`vectors/fallback.yaml` —— 用**声明式的 mock 剧本**描述多源行为：

```yaml
description: Multi-locator fallback semantics
cases:
  - name: digest mismatch falls through to next locator
    locators: [mock://a, mock://b]
    sha256: "<hex of 'good'>"
    responses:
      mock://a: { status: 200, body_utf8: wrong }
      mock://b: { status: 200, body_utf8: good }
    expect:
      resolved_from: mock://b
      network_calls: 2
      blobs_written: 1              # 错的那份绝不落盘

  - name: 202 is not a success
    locators: [mock://a]
    sha256: "<hex of 'good'>"
    responses:
      mock://a: { status: 202, body_utf8: "" }
    expect:
      error: bad_status
      blobs_written: 0
```

另有 `vectors/{digest,cache_layout,manifest,index}.yaml`。

错误用**稳定的机器可读代码**（`missing_version` / `digest_mismatch` /
`bad_status` / `all_locators_failed`），不比对人类可读消息——那必然跨语言不一致。

### mock registry

一个极小的 HTTP 服务，按剧本回放响应并记录调用次数。用 Python 实现（TS 端也连它，
避免两份 mock 再漂移一次）。以子进程方式启动，端口写入环境变量。

### 缓存布局向量

```yaml
description: Content-addressed blob paths
cases:
  - sha256: abcd1234…
    expect_path: blobs/sha256/ab/abcd1234…
```

两端断言相对 `$MOLHUB_HOME` 的**完整相对路径字符串**。这条让 Python 与 TS 客户端
同机共享缓存互相命中——是布局被冻结进 `CLAUDE.md` 的原因。

### 运行器契约

每种语言写一个薄运行器：读向量 → 调本语言实现 → 断言。运行器可以有语言特色，
**向量文件一个字节都不许改**。向量若需修改，改的是契约本身，两端同时受影响。

### 放置

向量与 mock 放 `molhub-index` 仓（02 已建），与 schema 同处一地——它们共同构成
「非代码的真相源」。Python 运行器留在本仓，以 git submodule 或 CI 下载方式取用向量。

## 用户侧 API 示例

本 spec 对最终用户无 API。面向的是**实现者**：

```bash
# 本仓 CI 中
$ uv run pytest tests/conformance/ -v
tests/conformance/test_vectors.py::test_coordinate[shorthand expands to defaults] PASSED
tests/conformance/test_vectors.py::test_coordinate[missing version is rejected]   PASSED
tests/conformance/test_vectors.py::test_fallback[digest mismatch falls through]   PASSED
tests/conformance/test_vectors.py::test_cache_layout[sha256 two-char shard]       PASSED
...
42 passed
```

```bash
# 未来 molhub-js 仓 CI 中，同一批向量
$ npm run test:conformance
  ✓ coordinate › shorthand expands to defaults
  ✓ coordinate › missing version is rejected
  ✓ fallback › digest mismatch falls through to next locator
  42 passed
```

新增一条跨语言约束的完整流程：

```bash
# 1. 在索引仓加一个用例
$ vim molhub-index/conformance/vectors/fallback.yaml
# 2. 两端 CI 立刻变红，直到各自实现跟上
```

## Files

| 动作 | 路径 |
|---|---|
| new(外仓) | `molhub-index/conformance/vectors/{coordinate,digest,fallback,cache_layout,manifest,index}.yaml` |
| new(外仓) | `molhub-index/conformance/mock_registry/`（可独立启动的 mock 服务） |
| new(外仓) | `molhub-index/conformance/README.md` — 运行器契约、如何新增用例 |
| new | `tests/conformance/test_vectors.py` — Python 运行器 |
| new | `tests/conformance/conftest.py` — mock registry 生命周期 fixture |
| edit | `.github/workflows/ci.yml` — 新增 conformance job |

## Tasks

- [ ] Add 向量文件 schema（向量自身也要可校验，防止手写出错）
- [ ] Add `vectors/coordinate.yaml` — 全称/简写/各类非法输入
- [ ] Add `vectors/digest.yaml` — sha256 计算、前缀解析、比对
- [ ] Add `vectors/cache_layout.yaml` — 分片路径、边界 hex
- [ ] Add `vectors/fallback.yaml` — 首个成功 / 首个 404 转次个 / digest 不符转次个 / 全失败
- [ ] Add `vectors/manifest.yaml` — 合法样本 + 缺 sha256 负样本 + 未知 schema_version
- [ ] Add `vectors/index.yaml` — 索引加载与检索
- [ ] Add mock registry 服务（剧本回放 + 调用计数 + 子进程启动）
- [ ] Add 稳定错误码枚举，并写进 conformance README
- [ ] Add Python 运行器，用 pytest 参数化把每个 case 展开为独立测试
- [ ] Add CI conformance job，向量以固定 ref 取用（不追 index 仓 HEAD，避免红得莫名）
- [ ] Add README：如何新增一条用例、两端的更新义务

## Testing

- 运行器自身要有一个「元测试」：故意提供一份必失败的向量，断言运行器确实报错——
  防止运行器写成永远通过的空壳。
- 向量覆盖率用清单核对：01 与 02 的 acceptance 里每一条 `runtime` 类型的
  criterion，都要能对应到至少一条向量，或在 README 中明确记为「语言特有、不入向量」。
- mock registry 的调用计数断言用于验证「缓存命中不发网络请求」跨语言一致。

## Out of scope

- TypeScript 运行器与实现（→ 04；本 spec 只保证向量对它可用）
- 前端（→ 05）
- 性能基准
- 真实网络集成测试（向量全部走 mock）
