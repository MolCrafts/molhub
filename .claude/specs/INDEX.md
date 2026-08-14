- [streaming-data-tiers-01-strategy](streaming-data-tiers-01-strategy.md) — remote/rolling/ready 三层分级 + 传送带流水线策略之锚；后继 -02 块格式[molnex]、-03 传送带[molhub]、-04 调度集成[molnex]。 [approved]
- [streaming-data-tiers-03-conveyor-01-ledger](streaming-data-tiers-03-conveyor-01-ledger.md) — Conveyor 基座：BlockId + 四态状态机 + 崩溃安全 JSONL 台账与 TTL 租约（I5/I9）。 [approved]
- [streaming-data-tiers-03-conveyor-02-roster](streaming-data-tiers-03-conveyor-02-roster.md) — REMOTE 层块名册（registry manifest 投影）+ 有界重试 digest 校验传输（I1/I6）。 [approved]
- [streaming-data-tiers-03-conveyor-03-prepare](streaming-data-tiers-03-conveyor-03-prepare.md) — 准备阶段：拆分路由、单元完整的块生产（懒导入 molnex BlockWriter，I2/I7）。 [approved]
- [streaming-data-tiers-03-conveyor-04-residency](streaming-data-tiers-03-conveyor-04-residency.md) — 字节预算驻留、背压队列与工作池、覆盖报告、采样器元数据交接（I3/I4/I9/I10）。 [approved]
# MolHub product specifications

这里保存 MolHub 的长期产品合同。与一次性 implementation spec 不同，
`molhub-product-*` 在实现完成后**不删除**：状态从 `approved` → `in-progress` →
`implemented`，产品边界变化时原地更新，并在 acceptance 中保留尚未完成的门禁。

状态含义：

- `implemented`：当前仓内实现满足主要合同；仍可有后续强化项；
- `in-progress`：代码已存在，但生产或完整产品闭环尚未完成；
- `approved`：方向已确认，可以进入实现；
- `proposed`：仍需产品决策。

## Chain: molhub-product

| Position | Spec | Status | Outcome |
|---:|---|---|---|
| 00 | [产品定位与仓库边界](molhub-product-00-positioning-boundaries.md) | implemented | MolHub product monorepo；registry data-only；生态能力边界 |
| 01 | [Coordinate、Manifest 与 Registry](molhub-product-01-registry-contract.md) | implemented | 单一 schema、固定版本、deterministic registry snapshot |
| 02 | [多语言客户端与 Transport](molhub-product-02-clients-transport.md) | implemented | Python/TypeScript/CLI、cache、sources、datasets、conformance |
| 03 | [Artifact onboarding](molhub-product-03-artifact-onboarding.md) | in-progress | 外部平台发布、Web/GitHub 提交、D1 审核和 registry PR |
| 04 | [Web Catalog 与视觉语言](molhub-product-04-web-catalog-design.md) | implemented | TanStack Start + Rsbuild + Rstest、tokens、catalog/detail/submit |
| 05 | [MolHub Inspector](molhub-product-05-inspector.md) | in-progress | MolVis + MolPlot vertical slice；MolRec/Zarr 与 atom/environment 仍待数据面 |
| 06 | [文档、发布与 Registry 运营](molhub-product-06-docs-operations.md) | in-progress | Docs/release/health 已实现；正式 Web/API 部署仍待生产凭据 |
| 07 | [Live Registry 分发](molhub-product-07-live-registry-distribution.md) | proposed | 官方静态 snapshot、显式更新、离线 cache/bundled fallback、跨 SDK revision |
| 08 | [Catalog 2.0](molhub-product-08-catalog-v2.md) | proposed | 20+ curated families、版本比较、科学 facets、kind profiles 与 UI 信息架构 |
| 09 | [Assisted Onboarding](molhub-product-09-assisted-onboarding.md) | proposed | DOI/source URL import、证据化预填、向导式 manifest 与安全 metadata API |
| 10 | [Reproducible Projects](molhub-product-10-reproducible-projects.md) | proposed | molhub.toml/lock、多 artifact sync、drift、citation 与跨 SDK parity |

每份 spec 都有同名 `.acceptance.md`。Acceptance status 比 spec 顶层状态更细；不得为了
让整份 spec 看起来完成而把 production、visual 或 cross-repo criteria 提前标绿。

## Implementation chain: python-native-dataset-protocol

Python-native dataset 定义协议（`@dataset` + `load()` → 集合）。一次性实施链；完成后由 `mol:close` 删除。不替代 product-01 YAML registry，只修订 product-02 的 Python dataset 段。

| Position | Spec | Status | Outcome |
|---:|---|---|---|
| 01 | [声明面：装饰器、清单、编目](python-native-dataset-protocol-01-types.md) | approved | `@dataset` + `DatasetManifest` + `Datasets`；FrameCollection 评估：不引入 molpy 类层次 |
| 02 | [资源助手 fetch/open/cache_dir](python-native-dataset-protocol-02-helpers.md) | approved | 实例 `.fetch` / `.open` / `.cache_dir`；构造不取字节 |
| 03 | [load() 与 QM9 参考实现](python-native-dataset-protocol-03-load.md) | approved | 定义类不再是 Dataset；`load()` 返回 PyTorch 对齐的 InMemoryDataset |
| 04 | [迁移 RevMD17 / ThreeBPA / CSV](python-native-dataset-protocol-04-migrate.md) | approved | 与 QM9 同一交互；CSV 无假坐标 |
| 05 | [迁移 Zinc / Phalkethoh](python-native-dataset-protocol-05-mm.md) | approved | load() → Frame 集合；删除 MolecularFrame / MoleculeSplit |
| 06 | [公开面 resolve 与文档](python-native-dataset-protocol-06-surface.md) | approved | `from molhub.dataset import QM9`；包级 `resolve` |

## Implementation chain: molhub-delivery

这是 2026-08-09 对 product 01–06 审计后产生的一次性实施链；完成后由 `mol:close`
删除，不替代上面的 durable product contracts。

| Position | Spec | Status | Outcome |
|---:|---|---|---|
| 02 | [Inspector 生命周期证据](molhub-delivery-02-guard-inspector.md) | code-complete | 自动证明 role/route 取消与 dispose；扩充 keyboard/mobile-light 证据 |

## Scientific collection chain: universal-class-i-dataset

This chain owns source registration, physical-role composition, provenance,
group identity, derived subsets, global molecular identity, split policy, and
frozen evaluation collections. MolNex remains dataset-agnostic; a Molexp
experiment consumes the pinned MolHub collection and owns task scheduling and
run-specific configuration.

| Position | Spec | Status | Outcome |
|---:|---|---|---|
| 01 | [Universal Class-I dataset composition](universal-class-i-01-dataset-composition.md) | approved | THEMol-first task collection, derived relaxation subset, hierarchical identity/splits, OMol25/OPoly26 evolution |

## Feature coverage

| 之前讨论的能力 | 规范位置 |
|---|---|
| 前端、Python API、REST API、语言绑定、registry 怎么分 | 00 |
| `apps/web` 为什么在 apps、以后放什么 | 00、04 |
| `molhub-registry` 只是数据库 | 00、01 |
| coordinate、manifest、locator、digest、cache | 01、02 |
| 单一契约，消灭重复校验 | 01、02 |
| Python SDK、TypeScript SDK、CLI、未来其他语言 | 02 |
| dataset adapters 与统一 Frame/Target interface | 02、python-native-dataset-protocol-01..06 |
| 上传到 Figshare/Hugging Face | 03 |
| 网站提交 manifest，不强迫 GitHub | 03 |
| GitHub 直接 YAML 贡献 | 03 |
| REST submission/review/webhook API | 03 |
| 统一视觉 tokens、完整 redesign、简洁文案 | 04 |
| NGC 风格 catalog card 信息密度 | 04 |
| Rsbuild + Rstest + TanStack Start | 04 |
| MolVis 可视化和 Chemiscope 类 Inspector | 05 |
| MolRec/Zarr 派生预览与大数据 streaming | 05 |
| Zensical 文档、发布、registry 巡检 | 06 |
| Registry merge 后旧 SDK 无需发版即可看到新 entry | 07 |
| Registry CDN、显式 update、离线与 rollback | 07 |
| Artifact families、version switch/compare、scientific facets | 08 |
| Dataset/model/plugin typed discovery profile | 08 |
| 从 DOI、Zenodo、Figshare、HF、GitHub 自动预填 manifest | 09 |
| Submission drafts、import evidence 与 SSRF boundary | 09 |
| 多 coordinate 项目、deterministic lock 与 sync | 10 |
| 离线 citation、registry drift 与 project provenance | 10 |

## Recommended execution order

1. 完成 03/06 尚未通过的 production gates：正式 D1/API/Web、真实 submission→PR→merge
   smoke、registry dispatch/revision；
2. 评审并实现 07，让 registry 数据更新与 SDK 发版解耦，同时保留默认 offline resolve；
3. 实现 08 Phase 1–3：诚实的 kind UI、production-sized curated catalog、scientific facets、
   artifact family/version comparison 和视觉矩阵；
4. 继续 05（它是 Inspector 2.0 的唯一真相源）：在 MolVis/MolRec 边界补 remote primitives、
   derived store，再扩 revMD17/QM9/Polymer Tg 和 atom/environment linking；
5. 实现 09 的 Zenodo vertical slice，再扩 Figshare/HF/GitHub 与 production import smoke；
6. 实现 10 的 Python deterministic lock/sync，再做 Node parity 与 citation；
7. 只有 kind profile schema 和真实内容都准备好后，执行 08 Phase 4 并在首页推广 model/plugin。

07–10 当前为 `proposed`。进入实现前逐份确认产品选择，尤其是 07 的“显式更新而非默认联网”、
08 的 20-family launch gate、09 的 allowlisted importer boundary，以及 10 的 pinned-only intent。

## Superseded specs

旧 `registry-core-02`–`06` 是迁移期 implementation specs，包含已经推翻的假设：独立
`molhub-js/molhub-app` 仓、`molhub-index` 名称、content-addressed cache、强制 MolHub
自行计算 SHA-256，以及网站不能提交 manifest。它们由本产品链取代，不应恢复为真相源。

## Closed external programs

The former MM parameter-validation baseline chain in MolNex is closed and is
not an authority for current dataset selection or production submission.
