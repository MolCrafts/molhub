---
spec: registry-core-05-app
created: 2026-08-06
criteria:
  - id: ac-001
    summary: "站点为纯静态产物"
    type: runtime
    pass_when: "构建输出仅含 HTML/CSS/JS/静态资源，无服务端进程，可由任意静态文件服务器托管并正常浏览与检索"
    status: pending
  - id: ac-002
    summary: "索引中每个 artifact 都有可达详情页"
    type: runtime
    pass_when: "对索引中全部 artifact 遍历其详情页 URL，无一返回 404"
    status: pending
  - id: ac-003
    summary: "调用片段与真实 API 一致"
    type: runtime
    pass_when: "详情页生成的 Python 片段可被原样执行并成功取回该坐标；TS 片段通过类型检查；CLI 片段退出码为 0"
    status: pending
  - id: ac-004
    summary: "片段使用全称坐标"
    type: code
    pass_when: "生成的三语言片段中坐标均为 kind:namespace/name@version 全称形式，无简写"
    status: pending
  - id: ac-005
    summary: "检索无需服务端"
    type: runtime
    pass_when: "在断网且仅有静态文件服务器的环境下搜索关键字能返回匹配结果"
    status: pending
  - id: ac-006
    summary: "构建期不依赖外网"
    type: runtime
    pass_when: "将索引来源指向本地目录后，断网环境下构建成功并产出完整站点"
    status: pending
  - id: ac-007
    summary: "manifest 解析复用 TS 客户端"
    type: code
    pass_when: "src/ 通过 @molcrafts/molhub-browser 读取索引，未自行实现 manifest 或坐标解析"
    status: pending
  - id: ac-008
    summary: "品牌 token 与文档主题逐字节一致"
    type: runtime
    pass_when: "src/styles/brand-tokens.css 与 molcrafts-zensical-theme 的 stylesheets/tokens.css 字节比对相同"
    status: pending
  - id: ac-009
    summary: "shadcn 原语未被手改"
    type: code
    pass_when: "src/components/ui/ 下文件与 shadcn 生成结果一致，无手工编辑痕迹"
    status: pending
  - id: ac-010
    summary: "三种非常态有明确界面"
    type: runtime
    pass_when: "索引为空、坐标不存在、artifact 无可用 locator 三种情况各自渲染出说明性界面而非空白或堆栈"
    status: pending
  - id: ac-011
    summary: "键盘可达与对比度达标"
    type: runtime
    pass_when: "详情页与搜索可全程键盘操作，自动化可访问性检查在正文文本上无对比度违规"
    status: pending
  - id: ac-012
    summary: "深浅色与窄屏适配"
    type: runtime
    pass_when: "在深色与浅色偏好下均可读，且 375px 宽视口下正文不出现横向滚动"
    status: pending
  - id: ac-013
    summary: "质量门与生态一致"
    type: runtime
    pass_when: "npm run lint（Biome）与 npm run typecheck（tsc --noEmit）均通过"
    status: pending
  - id: ac-014
    summary: "索引更新可触发站点重建"
    type: runtime
    pass_when: "索引仓合入一个新 manifest 后，部署工作流被触发并使该 artifact 的详情页可访问"
    status: pending
out_of_scope:
  - "后端服务、数据库、账号、下载量统计、网页端上传"
  - "服务端检索"
  - "分子结构可视化预览"
  - "molcrafts.org/molhub/ 落地页（属 molcrafts-index 仓）"
  - "文档站（registry-core-06）"
  - "国际化"
---

# Acceptance — registry-core-05-app

「完成」= 一个人能在 `app.molcrafts.org/molhub/` **找到**一个数据集，并**知道
怎么在自己代码里用它**——全程不需要任何后端在运行。

## AC-001 / AC-005 / AC-006 — 零后端是可验证的，不是自我声明

三条从不同角度钉同一件事：产物是静态的（ac-001）、检索在客户端（ac-005）、
构建不依赖外网（ac-006）。任何一条不成立，「phase 1 无后端」这个前提就破了，
而它是整个早期架构成本可控的基础。

ac-006 同时保障 CI 可靠性与离线开发——不能因为 CDN 抖动就构建不出站点。

## AC-003 / AC-004 — 片段过期是这类站点最伤人的失败

用户从站上复制一段代码、粘进去跑不通——这比没有片段更糟，因为它消耗信任。
因此 ac-003 要求**真的执行**：Python 片段实跑，TS 片段过类型检查，CLI 片段跑通。
不接受「人工检查过了」。

ac-004 要求全称坐标：复制走带简写的片段，换个 namespace 就失效，而失效原因
完全不明显。

## AC-002 — 覆盖全部 artifact，不是抽查

遍历索引全量。静态站没有理由留下死链，且这条能顺带发现索引里的畸形条目。

## AC-007 — 前端不是第三套实现

若前端自己解析 manifest，molhub 就有三套需保持一致的实现，而这套还不在
conformance 覆盖内。必须走 04 的 `browser` 包。静态 grep 判定。

## AC-008 / AC-009 — 与既有生态对齐，不另起炉灶

`molcrafts-index` 的 `CLAUDE.md` 已明文规定品牌 token 必须与
`molcrafts-zensical-theme` 逐字节相同，且 `src/components/ui/` 不得手改。
本仓沿用同一约定——**这两条不是本 spec 发明的，是既有约定的延续**，因此用同样
的机械方式检查。

## AC-010 — 非常态是常态

索引为空（新部署）、坐标不存在（用户改 URL）、artifact 全部 locator 失效
（上游真的挂了）——三种都会发生。渲染堆栈或白屏不合格。

## AC-011 / AC-012 / AC-013 — 给研究者用的目录

信息密度优先，但可访问性不是可选项。质量门与 `molcrafts-index` 保持一致
（Biome + tsc），这样两个仓之间人员流动时不需要切换心智。
