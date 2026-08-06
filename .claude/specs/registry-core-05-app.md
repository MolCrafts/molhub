---
slug: registry-core-05-app
status: approved
created: 2026-08-06
chain: registry-core
position: 5
depends_on: [registry-core-04-ts-client]
scope_layer: cross-repo (molhub-app)
---

# registry-core-05-app — registry 浏览应用（Rsbuild + shadcn）

## Summary

一个**零后端**的静态单页应用，浏览与检索索引中已注册的 artifact，并为每个
artifact 给出可直接复制的调用片段（Python / TypeScript / CLI）。

部署到 **`app.molcrafts.org/molhub/`**——按现有 MolCrafts URL 约定，这是「应用」
而非「落地页」也非「文档」。技术栈对齐 `molcrafts-index` 已在用的那一套。

## Domain basis

无物理内容。约束来自 MolCrafts 生态**已经成立的既有约定**（读自 `molcrafts-index`
仓的 `CLAUDE.md` 与 `package.json`，非臆测）：

| 约定 | 值 |
|---|---|
| URL：落地页 | `molcrafts.org/<product>/` — 由 `molcrafts-index` 提供 |
| URL：文档 | `docs.molcrafts.org/<product>/` — zensical，见 06 |
| URL：**应用** | `app.molcrafts.org/<product>/` ← **本 spec** |
| 构建 | Rsbuild（`@rsbuild/core` + `@rsbuild/plugin-react`） |
| UI | React 18 + TS strict + Tailwind v4 + Radix/shadcn（`style: new-york`，`baseColor: neutral`，`iconLibrary: lucide`） |
| 质量门 | Biome（`npm run lint`）+ `tsc --noEmit`（`npm run typecheck`） |
| 包管理 | npm（`molcrafts-index` 用 npm，不用 pnpm） |
| 品牌 token | `src/styles/brand-tokens.css` 必须与 `molcrafts-zensical-theme/.../stylesheets/tokens.css` **逐字节相同** |

本 spec 不发明新栈，照抄这一套。

## Design

### 仓库

新仓 `molhub-app`。**不并入 `molcrafts-index`**：那是品牌落地页，路由与
`PRODUCT_PAGES` 结构是为营销页设计的；registry 浏览是数据驱动的应用，二者
生命周期与发布节奏不同。

### 数据流

```
molhub-index (02)  ──build──▶  dist/index.json  ──CDN──┐
                                                        ▼
                         构建期 fetch  ──▶  molhub-app 预渲染每个 artifact 页
                                            运行期用 @molcrafts/molhub-browser (04) 解析
```

**不自己解析 manifest**——用 04 的 `browser` 包。否则 molhub 会有第三套需保持
一致的实现，而这套还不在 conformance 覆盖内。

### 路由

Rsbuild 无内置路由；沿用 `molcrafts-index` 的做法（`src/lib/routes.ts` + 显式
页面映射，不引 react-router），构建期为每个 artifact 预渲染静态 HTML。

```
/molhub/                                  首页：kind 分区 + 搜索
/molhub/datasets                          列表，按 namespace 分组，license 过滤
/molhub/models
/molhub/plugins
/molhub/a/<kind>/<ns>/<name>/<version>    详情页
```

### 组件

shadcn 原语（`src/components/ui/`，**不手改**）+ 产品组件：

| 组件 | 职责 |
|---|---|
| `ArtifactCard` | 列表项：标题、坐标、license、大小 |
| `LocatorList` | 全部 locator + 各平台标识 + sha256（可复制） |
| `CodeTabs` | 三语言调用片段 + 一键复制（**核心功能**） |
| `TargetTable` | graph-level / atom-level 目标 |
| `VersionSwitcher` | 同 name 的多版本互链 |
| `SearchBox` | 客户端检索入口 |

检索：构建期用 Orama 建索引，运行期纯客户端。几千条目不需要服务端。

### 调用片段是核心功能

用户来这里的主要动作是「找到它，然后知道怎么用」。片段由坐标生成：

```python
# Python
from molhub import Molhub
hub = Molhub()
paths = hub.fetch("dataset:molcrafts/qm9@v2")
```

```ts
// TypeScript
import { Molhub } from "@molcrafts/molhub-node"
const hub = new Molhub()
const paths = await hub.fetch("dataset:molcrafts/qm9@v2")
```

```bash
# CLI
molhub fetch dataset:molcrafts/qm9@v2
```

坐标在片段中**永远用全称**——用户复制走简写后换个 namespace 就失效，且失效原因
完全不明显。

### 明确不做

无用户账号、无下载量、无评论评分、无网页端上传、无服务端检索。这些都要后端，
而后端的引入应由真实需求驱动，不是由「网站看起来应该有」驱动。

## 用户侧「API」示例

对外契约是 URL 形状与片段正确性：

```
https://app.molcrafts.org/molhub/
https://app.molcrafts.org/molhub/datasets?license=CC0-1.0
https://app.molcrafts.org/molhub/a/dataset/molcrafts/qm9/v2
```

详情页给出的片段必须可直接运行——从页面复制、未经修改：

```python
from molhub import Molhub
hub = Molhub()
paths = hub.fetch("dataset:molcrafts/qm9@v2")
```

贡献路径（页面上给出，指向索引仓）：

```bash
git clone https://github.com/MolCrafts/molhub-index
cp artifacts/dataset/molcrafts/qm9/v2.yaml artifacts/dataset/me/mydata/1.yaml
$EDITOR artifacts/dataset/me/mydata/1.yaml   # sha256 留空，bot 会回填
gh pr create
```

## Files

全部在新仓 `molhub-app`：

| 动作 | 路径 |
|---|---|
| new | `rsbuild.config.ts`、`biome.json`、`components.json`、`tsconfig.json`、`package.json` |
| new | `src/styles/brand-tokens.css` — 从 `molcrafts-zensical-theme` 逐字节复制 |
| new | `src/styles/tailwind.css` — anchors → shadcn CSS vars |
| new | `src/lib/{routes,index-loader,snippets,search}.ts` |
| new | `src/components/{ArtifactCard,LocatorList,CodeTabs,TargetTable,VersionSwitcher,SearchBox}.tsx` |
| new | `src/components/ui/` — shadcn 原语（生成，不手改） |
| new | `src/pages/{Home,Datasets,Models,Plugins,ArtifactDetail}.tsx` |
| new | `scripts/postbuild.ts` — 预渲染 + sitemap |
| new | `test/` — 片段生成与路由单测 |
| new | `.github/workflows/{ci,deploy}.yml` |

## Tasks

- [ ] Add Rsbuild + React 18 + TS strict + Tailwind v4 骨架，对齐 `molcrafts-index` 配置
- [ ] Add shadcn 初始化（`new-york` / `neutral` / `lucide`），生成所需原语
- [ ] Add `brand-tokens.css`，从 `molcrafts-zensical-theme` 逐字节复制并加漂移检查
- [ ] Add `index-loader.ts` — 构建期 fetch `index.json`，支持指向本地索引以便离线开发
- [ ] Add 路由表与构建期预渲染（每个 artifact 一个静态 HTML）
- [ ] Add `ArtifactCard` 与三个列表页（kind 分区、namespace 分组、license 过滤）
- [ ] Add `ArtifactDetail` 页：标题、license、citation（可复制 BibTeX）、大小
- [ ] Add `LocatorList` — 全部 locator + sha256 + 平台标识
- [ ] Add `CodeTabs` — 由坐标生成三语言片段 + 一键复制
- [ ] Add `TargetTable` 与 `VersionSwitcher`
- [ ] Add Orama 构建期检索索引 + `SearchBox`
- [ ] Add 空状态与错误状态（索引为空、坐标不存在、locator 全失效）
- [ ] Add 深浅色与窄屏适配、键盘可达
- [ ] Add CI：`npm run lint` + `npm run typecheck` + 单测
- [ ] Add 部署工作流；索引仓更新触发重建

## Testing

- **片段正确性是最重要的一条**：单测断言由坐标生成的三语言片段与 02/04 的实际
  API 签名一致。片段过期是这类站点最伤用户的失败。
- 路由测试：索引中每个 artifact 都能生成一个可达页面，无 404。
- 构建期无网络也能出站（指向本地索引），保证 CI 与离线开发可行。
- 品牌 token 漂移检查：与 `molcrafts-zensical-theme` 的 `tokens.css` 做字节比对。
- 可访问性：键盘可达、对比度达标、搜索框有 label。

## Out of scope

- 后端服务、数据库、账号、下载量统计、网页端上传
- 服务端检索
- 制品内容预览（分子结构可视化）——需要 L3 解析，本链不做
- `molcrafts.org/molhub/` 落地页（属 `molcrafts-index` 仓）
- 文档站（→ 06）
- 国际化（先英文单语）
