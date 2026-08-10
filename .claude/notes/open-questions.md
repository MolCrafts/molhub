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
- ~~`RevMD17Dataset(download=True)` 名不副实~~ — 已修。revMD17 迁到
  `dataset:molcrafts/revmd17@v4`（Figshare article 12672038 v4，每个分子一个
  role），`download=True` 现在真的经 `Molhub` 取回。
- ~~实际缓存路径与冻结的布局契约不符~~ — 已修，选了 (a)。新增
  `Coordinate.cache_path()` 组键，`Molhub.fetch` 与 `cli.cache_verify` 两处调用点
  同时改；`tests/test_molhub.py` 那条 `"qm9@v2" in str(path)` 的宽断言换成整条
  相对路径相等，`tests/test_cli.py` 的 `_cache` 助手也改成从坐标派生而非手写。
  契约文本未动——错的是代码，不是契约。

## 已结清：仓库拓扑

- `molhub` 是产品 monorepo：Python SDK、`packages/typescript`、`apps/web`、
  `apps/api`、`packages/registry-tools`、`spec/`。
- `molhub-registry` 是 data-only 仓，只存 `artifacts/**/*.yaml` 与调用主仓工具链的 CI。
- 不再创建 `molhub-js` 或 `molhub-app`；语言包在 `packages/`，可部署应用在 `apps/`。
- contract 和 conformance 必须跟实现同一提交演进，因此归 `molhub/spec`，不归数据库仓。

## 2. 缺类型检查器

`mol_project.build.check` 只有 `ruff check` + `ruff format --check`，没有 Python
canonical 三件套里的第三件（`ty` 或 `mypy`）。CI 与 pre-commit 同样没有。

这次 molpy 迁移暴露了代价：`Frame.metadata` → `Frame.meta` 是纯属性重命名，
类型检查器本可在 CI 里当场拦下，实际却是运行时 `AttributeError`，而且
`frame.meta.update()` 那条**连异常都不抛**。引入 TypeScript 客户端后风险放大。

**已取证（2026-08-06），只差一次拍板。** `ty` 已装进 `dev` extra 并配好，
但**没有**接进 tox / CI / pre-commit——装了不设门是诚实的中间态，设一个人人学会
无视的红灯比没有更糟。

选 `ty` 而非 `mypy` 的决定性证据：molpy **不带 `py.typed`**。mypy 因此把 `Frame`
整个当成 `Any`，对着 `f.metadata` 只报一句 `import-untyped`；`ty` 读 molpy 源码，
直接报 `unresolved-attribute`。**当初引出本条待决项的那个事故，`ty` 抓得住，
mypy 抓不住。**（诚实的边界：`frame.meta.update(...)` 那条静默失效两者都抓不住，
它类型上完全合法，只能靠 `test_meta.py` 那条回归测试。）

`ty check src/` 现在**全绿**——它报出的两个真 bug（`Coordinate.coerce` 与
`Locator.coerce` 在 `cls` 上做 `isinstance` 收窄，子类调用会把已解析对象送进
字符串分支炸在 `text.strip()`）已修。仅对 `huggingface.py` 关掉
`unresolved-import`，因为 `huggingface_hub` 是有意的可选 extra、lint 环境不装它。

待决只剩两问：**(1)** 要不要接进 CI 门禁；**(2)** 若接，放哪个环境。注意
`[tool.tox.env.lint]` 是 `skip_install = true`，把 `ty` 放进去能否解析到 molpy
没有验证充分，稳妥做法是放进装了包与 dev extra 的环境（CI lint job 里直接
`uv run ty check src/` 即可，那个 job 已经跑过 `uv sync --extra dev`）。
`tests/` 建议**不**纳入门禁：25 条诊断里有 5 条是 `pytest.raises` 里故意写非法
赋值，且 `ty` 不认 `# type: ignore[code]` 这种带码的 mypy 写法。

## 3. molpy 版本跟踪策略

依赖已收紧为 `molcrafts-molpy>=0.12,<0.13`。molpy 是 pre-1.0 且在小版本间搬公开
API（0.3 → 0.9 搬了 `Frame`/`Block`/`Element` 并重命名了 `metadata`）。

待决：谁在 molpy 发新小版本时负责验证并抬上界？是否需要一个定期跑 molpy
最新版的 CI 任务，让不兼容尽早以红灯出现而不是等用户撞上。

## 4. 按裸 URL 寻址的缓存要不要继续存在

原问题「`qm9.py:_download` 与 `csv_dataset.py:_download` 逐字重复」**已解决**：
两处 `_download` 均已删除，安全传输统一由 `molhub.sources` 的
`HttpsSource.fetch` 承担，数据源侧经 `DownloadCache` 调用它。
`csv_dataset.py` 的 `_resolve_cache_path` / `_resolve_cache_path_static` 双胞胎
也随之收进 `DownloadCache`。缓存根也已统一：`DownloadCache` 现在构造一个
`BlobStore` 读它的 `root`，解析规则只剩一份实现，顺序是
`$MOLHUB_HOME` → 弃用的 `$MOLHUB_CACHE_DIR`（仅在前者未设时读，且发
`DeprecationWarning`）→ `~/.cache/molhub`；下载落在 `urls/`，与契约里的 `files/`
互不相扰。

**仍然开放的是 `DownloadCache` 该不该长期存在。** 它的存在理由只有一条：这些源
按裸 URL 寻址、没有坐标，因而没有 `BlobStore` 能用的键。02 的数据源迁移
（revMD17 / 3BPA / CSV 改经 `Molhub`）做完后，这条理由对**registry 里的**数据集就不
成立了——那时 `DownloadCache` 是收敛成 `BlobStore` 的一层薄适配，还是整个删掉？

卡住这个决定的是 `CSVDataset("https://…/x.csv")`：这个公开入口允许用户传任意
URL，那类调用**永远**不会有坐标，因此「整个删掉」不一定成立。需要先决定裸 URL
入口是否继续支持——若支持，`urls/` 这套按文件名寻址的布局就得长期留着，并且要写清
它**不**属于跨客户端共享的布局契约（CLAUDE.md 只承诺
`files/<kind>/<ns>/<name>@<ver>/<role>`）。

## 5. 迁移前写入的缓存会失效一次

上一条的修复把落盘路径从 `files/dataset_molcrafts/…` 改成契约规定的
`files/dataset/molcrafts/…`。已经按旧路径缓存过的文件因此变成不可见，会被重下
一次。本仓是 alpha（`Development Status :: 3 - Alpha`）且旧路径从来不是承诺过的
形态，故未写迁移代码。

待决：0.1 的发版说明要不要点名这条，还是当作 alpha 期的正常损耗。
