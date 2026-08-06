# `.claude/notes/` — 被动项目知识

本目录存放**长期存活**的内部上下文：决策、蓝图、契约、债务、待决问题。
它服务于 agent 与维护者，**不是**面向用户的公开文档。

与相邻目录的分工：

| 目录 | 性质 | 内容 | 生命周期 |
|---|---|---|---|
| `README.md`（仓库根） | 公开 | 面向用户的说明与快速上手 | 随产品演进 |
| `.claude/notes/`（本目录） | **被动** | 决策、蓝图、待决问题、债务 | 比任何单个功能都长寿 |
| `.claude/specs/` | **主动** | 正在实施的 spec，`/mol:impl` 边做边勾选，完成即删除 | 短暂 |
| `.claude/agents/`、`.claude/skills/` | 运行时配置 | Claude Code 的 agent / skill 定义 | 随 harness |

## 文件

- `notes.md` — 演进中的决策记录，由 `/mol:note` 写入（同步式，不是只追加）
- `architecture.md` — 项目蓝图（模块、公开面、层次职责），由 `/mol:map` 填充；
  `librarian` 在 `/mol:spec` 第 4.5 步消费它做复用与放置建议
- `open-questions.md` — 尚未定论的问题，随时间逐条收敛

## 约束

- 不要把 spec 放这里（属于 `.claude/specs/`）
- 不要把面向用户的教程放这里（属于 `README.md` 或未来的 `docs/`）
- 不要把这里的内容复制进 `CLAUDE.md`——`CLAUDE.md` 是薄路由，指路而非内嵌
