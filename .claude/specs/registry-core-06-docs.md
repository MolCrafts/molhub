---
slug: registry-core-06-docs
status: approved
created: 2026-08-06
chain: registry-core
position: 6
depends_on: [registry-core-02-coordinate-index]
scope_layer: docs (in-repo)
---

# registry-core-06-docs — Zensical 文档站

## Summary

用 **Zensical + `molcrafts-zensical-theme`** 在本仓建立 molhub 的文档站，发布到
**`docs.molcrafts.org/molhub/`**：叙事型指南（怎么用）+ mkdocstrings 自动生成的
API 参考（有什么）。

与 05 的分工是硬的：**05 是目录**（有哪些数据集，怎么取），**06 是手册**
（molhub 这个库怎么用，怎么扩展一个 registry，坐标语法是什么）。

## Domain basis

无物理内容。约束全部来自本机 `molcrafts-zensical-theme` 仓的实测事实（读自其
`README.md`、`pyproject.toml`、`examples/zensical.toml`，非臆测）：

| 事实 | 值 |
|---|---|
| 配置文件 | `zensical.toml`，`[project]` / `[project.theme]` / `[project.extra.molcrafts]` |
| 主题名 | `name = "molcrafts"` |
| 依赖组 | `[dependency-groups] docs = ["zensical>=0.0.45", "molcrafts-zensical-theme>=0.2.3"]` |
| 主题当前版本 | 0.2.9 |
| 产品标记 | `[project.extra.molcrafts] product = "…"` → `html[data-molcrafts-product]` |
| 强调色 | `accent` + `accent_soft`（后者省略时由前者推导） |
| API 参考 | 主题自带 mkdocstrings；molhub 是纯 Python，用 `python` handler（**不是**主题内置的 `cpp` handler，那个需要 doxygen） |
| 品牌 token | `molcrafts_zensical_theme/.../stylesheets/tokens.css` 是 05 的字节比对基准 |

## Design

### 放在本仓，不另开仓

文档与 docstring 同源：mkdocstrings 直接读 `src/molhub/` 的 Google 风格 docstring
（`mol_project.doc.style: google`，全仓已统一）。分仓会让文档与代码版本漂移。

```
molhub/
  zensical.toml
  docs/
    index.md              molhub 是什么、装、第一个例子
    concepts/
      coordinates.md      坐标语法与为什么必须带版本
      manifests.md        manifest 格式、digest 为什么必填
      cache.md            $MOLHUB_HOME 布局与跨语言共享
    guides/
      fetching.md         取数据集 / 模型 / 插件
      extending.md        写一个新 Registry 驱动
      publishing.md       用 publish 发布自己的数据
      migrating.md        从 QM9Source 等旧 API 迁移
    reference/            mkdocstrings 自动生成
      molhub.md
      registry.md
      dataset.md
```

### `zensical.toml`

```toml
[project]
site_name = "molhub"
site_description = "Unified addressing and verified fetching for molecular datasets, models, and plugins."
site_author = "MolCrafts"
site_url = "https://docs.molcrafts.org/molhub/"
docs_dir = "docs"
site_dir = "site"

[project.theme]
name = "molcrafts"

[project.extra.molcrafts]
product = "molhub"
# accent 待定：若 molcrafts-index 的 productAccents.ts 已为 molhub 定色，复用该值

[project.plugins.mkdocstrings]
default_handler = "python"

[project.plugins.mkdocstrings.handlers.python]
paths = ["src"]
```

### 与 05 的边界（不重复）

| 问题 | 归属 |
|---|---|
| 有哪些数据集？ | 05 —— 数据驱动，随索引变 |
| `qm9@v2` 怎么取？ | 05 详情页的片段 |
| 坐标语法为什么是这样？ | 06 concepts |
| 怎么写一个新 Registry？ | 06 guides |
| `Molhub.fetch` 的签名？ | 06 reference（自动生成） |

**06 不列举数据集**——那会与索引漂移。要看有哪些，链接到 05。

### 文档质量门

`zensical build --strict`（坏链接即失败）进 CI。`mol_project.build.check` 不动，
文档单独一个 job，避免拖慢主门禁。

## 用户侧 API 示例

本 spec 的产出是文档，可验证的对外契约是「文档里的例子跑得通」。因此每个代码块
都要能被抽出来执行：

````markdown
<!-- docs/guides/fetching.md -->
```python
from molhub import Molhub

hub = Molhub()
paths = hub.fetch("dataset:molcrafts/qm9@v2")
print(paths["main"])
```
````

`docs/guides/extending.md` 里的扩展示例同样必须可执行：

```python
from molhub.registry import Registry, RemoteFile, Locator, Drivers, Fetcher

class MyRegistry:
    scheme = "mine"

    def resolve(self, locator: Locator) -> list[RemoteFile]: ...
    def fetch(self, remote: RemoteFile, dest): ...

fetcher = Fetcher(drivers=Drivers.discover().with_driver(MyRegistry()))
```

本地预览：

```bash
uv sync --group docs
uv run zensical serve          # http://localhost:8000
uv run zensical build --strict
```

## Files

| 动作 | 路径 |
|---|---|
| new | `zensical.toml` |
| new | `docs/index.md` |
| new | `docs/concepts/{coordinates,manifests,cache}.md` |
| new | `docs/guides/{fetching,extending,publishing,migrating}.md` |
| new | `docs/reference/{molhub,registry,dataset}.md` — mkdocstrings 指令 |
| edit | `pyproject.toml` — `[dependency-groups] docs` |
| new | `.github/workflows/docs.yml` — build --strict + 部署 |
| new | `tests/test_docs_examples.py` — 抽取并执行文档代码块 |

## Tasks

- [ ] Add `[dependency-groups] docs`，钉住 `zensical` 与 `molcrafts-zensical-theme` 版本
- [ ] Add `zensical.toml`（主题 molcrafts、product=molhub、mkdocstrings python handler）
- [ ] Add `docs/index.md` — 一段话定位 + 装 + 第一个可跑的例子
- [ ] Add `docs/concepts/coordinates.md` — 语法、为什么必须带版本、简写规则
- [ ] Add `docs/concepts/manifests.md` — YAML 格式、digest 为什么必填（含 202 事故作为动机）
- [ ] Add `docs/concepts/cache.md` — `$MOLHUB_HOME` 布局、跨语言共享、`cache verify`
- [ ] Add `docs/guides/fetching.md`
- [ ] Add `docs/guides/extending.md` — 写一个新 Registry 驱动，端到端可跑
- [ ] Add `docs/guides/publishing.md` — `publish` 与提 manifest PR 两条路径
- [ ] Add `docs/guides/migrating.md` — `QM9Source` 等旧 API → `Molhub`；含 molpy 0.12 的 `Targets` 变更
- [ ] Add `docs/reference/*.md` — mkdocstrings 指令，覆盖全部公开类
- [ ] Add `tests/test_docs_examples.py` — 抽取代码块并执行
- [ ] Add `.github/workflows/docs.yml` — `zensical build --strict` + 部署到 `docs.molcrafts.org/molhub/`
- [ ] Add accent 色：若 `molcrafts-index` 已为 molhub 定色则复用，否则记为待决

## Testing

- **文档里的每个 Python 代码块都要能执行**（`tests/test_docs_examples.py`）。
  需要网络的块用显式标记跳过，但标记本身要可见——不允许静默跳过。
- `zensical build --strict` 在 CI 中必须通过：坏内链、缺失 anchor 即失败。
- mkdocstrings 覆盖检查：`molhub`、`molhub.registry`、`molhub.dataset` 的每个
  `__all__` 符号都在 reference 中出现。
- 主题渲染冒烟：构建产物中存在 `data-molcrafts-product="molhub"`。

## Out of scope

- registry 浏览应用（→ 05）
- `molcrafts.org/molhub/` 落地页（属 `molcrafts-index` 仓）
- 主题本身的修改（属 `molcrafts-zensical-theme` 仓）
- 中文翻译（先英文单语）
- C++ API 参考（molhub 无 C++）
