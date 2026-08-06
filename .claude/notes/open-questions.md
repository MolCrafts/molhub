# 待决问题

bootstrap（2026-08-06）盘查中发现、尚无定论的项。逐条收敛，解决后删除或迁入
`notes.md`。

---

## 已结清

- ~~`tests/` 不镜像 `src/`~~ — 已重排为 `tests/test_dataset/`、`tests/test_uploader/`，
  并补齐 `test_qm9.py`、`test_revmd17.py`、`test_meta.py`。覆盖率 62% → 95%。
- ~~QM9 的 HTTP 202 / 0 字节 bug~~ — 已修（status 检查 + 临时文件 + 原子改名 +
  `_is_cached` 拒绝 0 字节），并有回归测试锁定。
- ~~`science.required` 的边界~~ — 定为 `false`。molhub 不实现方程或数值算法。
  若未来归一化层开始做单位换算，需重新评估。

## 1. 仓库拓扑未定

倾向 3 仓：

- `molhub`（本仓，Python client）
- `molhub-js`（TS client + web 的 pnpm monorepo）
- `molhub-index`（manifest + JSON Schema + conformance fixtures，外部 PR 主战场）

唯一确定的是**索引必须独立于客户端仓**。`molhub-js` 是否与 web 合仓、
conformance fixtures 放索引仓还是单独的 `molhub-spec` 仓，待定。

## 2. 缺类型检查器

`mol_project.build.check` 只有 `ruff check` + `ruff format --check`，没有 Python
canonical 三件套里的第三件（`ty` 或 `mypy`）。CI 与 pre-commit 同样没有。

这次 molpy 迁移暴露了代价：`Frame.metadata` → `Frame.meta` 是纯属性重命名，
类型检查器本可在 CI 里当场拦下，实际却是运行时 `AttributeError`，而且
`frame.meta.update()` 那条**连异常都不抛**。引入 TypeScript 客户端后风险放大。

待决：是否引入 `ty`，以及是否纳入 CI 门禁。

## 3. molpy 版本跟踪策略

依赖已收紧为 `molcrafts-molpy>=0.12,<0.13`。molpy 是 pre-1.0 且在小版本间搬公开
API（0.3 → 0.9 搬了 `Frame`/`Block`/`Element` 并重命名了 `metadata`）。

待决：谁在 molpy 发新小版本时负责验证并抬上界？是否需要一个定期跑 molpy
最新版的 CI 任务，让不兼容尽早以红灯出现而不是等用户撞上。

## 4. `RevMD17Source(download=True)` 名不副实

`revmd17.py` 的 `download` 参数**从不下载**：`download=True`（默认）在文件缺失时
直接抛 `FileNotFoundError`，让用户手动去 `BASE_URL` 取。参数在撒谎。

真正实现它需要下载并解包一个含全部 10 个分子的归档，属于 Registry 传输层的活，
故留到该 spec 一并处理，不单独打补丁。

## 5. 两份重复的下载实现

`qm9.py:_download` 与 `csv_dataset.py:_download` 现在是逐字重复的安全下载实现
（status 检查 + 临时文件 + 原子改名）。这次为止血刻意保留重复，未做抽取——
它们的归宿是 Registry 驱动层的单一 `fetch` 契约，由架构 spec 收编。

同理 `csv_dataset.py` 的 `_resolve_cache_path` 与 `_resolve_cache_path_static`
函数体相同，等内容寻址缓存落地后一并消除。
