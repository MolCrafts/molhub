# 活跃 spec 索引

每个正在实施的 spec 一行。`/mol:spec` 写入，`/mol:impl` 完成后连同 spec 文件一并删除。

## chain: registry-core

按依赖顺序实施。01 已完成并删除（见 commit 历史）。02 起需要 `molhub-index` 外仓；
04–05 在 `molhub-app` / `molhub-js` 外仓；06 回到本仓。

- [registry-core-02-coordinate-index](registry-core-02-coordinate-index.md) — 坐标语法、YAML manifest schema、`Molhub` 门面与独立静态索引仓 [approved]
- [registry-core-03-conformance](registry-core-03-conformance.md) — 语言中立 YAML 测试向量 + mock registry，Python 端首个通过 [approved]
- [registry-core-04-ts-client](registry-core-04-ts-client.md) — TypeScript 客户端，须通过同一批 conformance 向量 [approved]
- [registry-core-05-app](registry-core-05-app.md) — `app.molcrafts.org/molhub/` 浏览应用（Rsbuild + React + shadcn），零后端 [approved]
- [registry-core-06-docs](registry-core-06-docs.md) — `docs.molcrafts.org/molhub/` 文档站（Zensical + molcrafts-zensical-theme） [approved]
