# 项目决策记录

由 `/mol:note` 维护。**同步式**：规则变了就改写/删除旧条目，不是只追加。

---

## 词汇表：Registry / Source / index，三个词各占一个意思

2026-08-07 定。**这是命名契约，不是风格偏好**；下面每一条都有人踩过。

| 词 | 指什么 | 在哪 |
|---|---|---|
| **Registry** | manifest 的目录（编目本身） | `molhub.registry`、`$MOLHUB_REGISTRY`、`molhub-registry` 仓、TS 的 `MolhubRegistry` |
| **Source** | 上游字节来源的驱动 | `molhub.sources`、`ZenodoSource`、`PublishingSource`、`$MOLHUB_SOURCE_BASE` |
| **index** | **只表示入口文件**，别无他义 | `index.html`、TS 的 barrel `index.ts`；领域含义一律不用这个词 |

**为什么 index 必须让位。** 它同时被 web 平台占着（`index.html` 是静态托管唯一
认的首页名，`index.ts` 是 TS 的 barrel 约定）。目录仓与浏览站合一之后，
`dist/index.json` 会紧挨着 `index.html`，而领域类型被迫写成 `index-data.ts`
——那个 `-data` 后缀就是冲突留下的伤疤。

**为什么目录叫 Registry 而不是 Catalog。** npm / Docker / vcpkg / Julia / Bazel
全部用 registry 指**目录**，没有一家用它指字节来源。Cargo 的定义最准：
registry 里面含有一个 index。

**为什么上游那层从 `Registry` 改名成 `Source`。** 原来的叫法是全生态的异类——
Zenodo、Figshare 自称的是 *data repository / archive*，不是 registry。而且那层的
文件本来就叫 `driver.py` / `drivers/`，类名早就和文件名对不上了。

**踩过的坑，改名时会重犯：**

1. `molcrafts-index` 是**另一个真实存在的仓**（molcrafts.org 落地页），不是本仓的旧名，
   任何批量替换都必须绕开它。
2. `app/rsbuild.config.ts` 的 entry 名 `index` 决定产出 `index.html`；改掉它站点会在
   自己根路径 404，而本地 `rsbuild preview` 看不出来。
3. 生成或同步的文件（`brand-tokens.css`、Python/TS 的 manifest schema bundle、四份
   bundled manifest）会被批量替换悄悄污染。schema 有漂移守卫拦住了，**`brand-tokens.css`
   没有守卫**——这是已知缺口。
4. 「下标」义的 index 不能动：`IndexError`、`tabIndex`、`indexOf`、
   `noUncheckedIndexedAccess`、QM9 原始数据里名为 `"index"` 的列、
   `MapDataset` 的 "index-addressable"。

**同一天顺手清掉的一处歧义**：`molhub.dataset` 的三个数据集读取器原名
`QM9Source` / `RevMD17Source` / `ThreeBPASource`，与传输层的 `Source` 协议
**不是**一回事——它们读的是已经落盘的字节，不实现 `resolve`/`fetch`。已改名为
`QM9Dataset` / `RevMD17Dataset` / `ThreeBPADataset`，与同模块早已存在的
`CSVDataset` / `InMemoryDataset` / `SubsetDataset` 一致。**不留 shim**：
`stage: experimental`，重构期不背历史包袱。

## 定位：目录 + 归一化，不做字节仓储

molhub 不托管大制品字节。分子数据集体量大（GB~TB）、再分发授权复杂，
自建存储既不划算也不合规。molhub 的价值在**归一化与可寻址**：任何来源的东西
都能通过一个稳定坐标取到、并被强制校验。字节留在上游（Zenodo / Figshare /
HuggingFace）。

**例外**：MolCrafts 自家插件走自建的小型 source（静态对象存储 + CDN）。
它必须实现同一套 `Source` 接口，**不得特例化**——如果它需要开后门，
说明接口抽错了。

## 间接层的真实理由（已修正）

`coordinate → locator[]` 这层间接**不是**为了防"链接腐烂"。上游标识确实稳定：
Zenodo 有 concept DOI + 版本 DOI 且逐文件公布 md5，HuggingFace 在 repo 内按
commit SHA / LFS sha256 内容寻址，Figshare DOI 持久。

它存在的真实理由是四条：

1. **DOI 不是字节** — DOI 解析到的是记录，仍需 `DOI → API → 文件列表 → 直链 → 校验`
2. **国内镜像** — `hf-mirror.com` 等，对中文用户群是刚需
3. **HF 命名空间可变** — commit SHA 内容寻址，但 `org/name` 可改名、删除、加 gating
4. **裸 HTTP 源** — 大量 MD 数据集挂在课题组服务器上，那些是真会失效的

## 失效模式是"未校验取回"，不是"链接失效"

实证（2026-08-06）：`https://figshare.com/ndownloader/files/3195404` 返回
**HTTP 202 / content-length 0**（Figshare 异步准备下载），链接本身活着。
而 `src/molhub/dataset/qm9.py` 的 `_download()` 不查 status，直接
`dest.write_bytes(r.read())` → 落盘 0 字节且不报错 → `_load_exclusion_list`
返回空集 → `_ensure_downloaded` 因 `exists()` 为真而永不重试 → QM9 加载
133,885 条而非 README 承诺的 130,831 条，**3,054 个未表征分子静默混入**。

由此立为硬规则，**并且这条事故真正证明的是传输契约，不是 digest**：fetch 必须
「查 status → 流式写临时文件 → 原子改名」，任一步失败即换下一个 locator；0 字节
文件一律当作不存在（否则失败会因 `exists()` 为真而永久固化）。这三步不依赖任何
digest 就能拦住 202、半截和错误响应。

> 本条曾写作「manifest 中 digest 必填，CI 拒绝无 digest 的条目，digest 由 bot
> 从上游 API 抓取或自行算出」。**已作废**，见下文「版本标识靠 DOI 与钉版本的
> locator，不靠 digest」：digest 可选、照抄上游、molhub 绝不自算。事故的教训被
> 误记成了「必须有 digest」，实际是「必须验状态并原子落盘」。
>
> 由这次事故派生的另一条仍然成立：`size` 不得为 0（见同一节），因为 size 可能是
> 一个 artifact 唯一的交叉检查，而 0 正是这次失败的形状。

**已落地**（2026-08-06）：`molhub.sources` 承担全部传输，五步 fetch 契约与
digest 强校验由 `HttpsSource` + `Fetcher` 实现，回归测试锁定 202、digest 不符、
传输中断三条失败路径。数据源的两处 `_download` 已删除，统一走 `DownloadCache`。
数据源本身尚未用 `Fetcher`——那要等 02 给它们 manifest digest。

## molpy 版本策略：小版本会搬公开 API

molpy 是 pre-1.0，且在小版本间移动公开 API。0.3 → 0.9 把 `Frame`/`Block`/
`Element` 从 `molpy.core.*` 搬到顶层，并把 `Frame.metadata` 改名 `Frame.meta`。
原先 `molcrafts-molpy>=0.3.0` 的开放下界让这次破坏性升级悄悄进了 lock，
origin/master 一度不可导入且 CI 未覆盖。依赖已收紧为 `>=0.16,<0.17`。

dev 分支上不再对 PyPI：`.github/partners.env` 让 molpy 与 molrs 跟踪各自的
`dev`，`[tool.uv.sources]` 指向兄弟目录 `../molpy`、`../molrs/molrs-python`，
CI 与 git hooks 都经 `scripts/partners.py` 解析到同一提交。`uv.lock` 提交且为
universal lock（跨架构开发）。

molrs 0.16 起 `Frame.meta` 是**实时、写穿**的 `FrameMeta` 映射：读出即裸 Python
值（向量为 tuple），原地 `frame.meta[k] = v` / `del` / `update` 都生效，写入裸值
即可（dtype 自动推断；需固定 dtype 时用 `mp.core.MetaValue`）。0.12 的两个
静默陷阱随之消失，原先封装它们的 `molhub.dataset.meta`（`Targets` /
`MetaCodec`）已删除，调用方直接用 `frame.meta`，构造时用
`Frame({"atoms": blk}, meta={...})`。

另注：`len(Block)` 是**列数**，行数是 `Block.n_rows`；`len(Frame)` 是 block 个数。

## 多语言绑定：规格先行

Python 与 TypeScript 两套客户端**必然漂移**，且靠 code review 兜不住。对策：

- JSON Schema（以 YAML 书写）定义 manifest / registry，唯一手写来源是本仓 `spec/`
- **语言中立的 conformance 测试套件**（YAML 测试向量 + mock source），
  两端必须同时通过：坐标解析、locator fallback 顺序、digest 校验失败路径、缓存布局
- 缓存磁盘布局写入规格，两端同机共享 `$MOLHUB_HOME` 互相命中
- `schema_version` 版本化

## 产品 monorepo + data-only registry

manifest 放在独立的 `molhub-registry` 仓，不放客户端仓。理由：外部贡献者提
manifest 不应需要客户端仓写权限，也不应触发库发版。硬编码上游 URL 的形态已经
消灭——四个数据源现在都只持有一个 `COORDINATE` 常量。

`molhub-registry` 只拥有 `artifacts/**/*.yaml`。Schema、validator、snapshot builder、
Python/TypeScript SDK、Web 和 REST API 全在 `molhub`。Registry CI checkout 主仓工具链
后验证数据；数据库 PR 不安装自己的 npm 工程，也不构建前端。

### schema 的所有权与生成副本

**`molhub/spec/manifest.schema.yaml` 与 `registry.schema.yaml` 是唯一手写真相源。**
`src/molhub/schema/manifest.schema.yaml` 是 wheel 的离线 bundle；
`packages/typescript/src/generated-manifest-schema.ts` 是 npm runtime bundle。
`npm run contract:sync` 单向生成两者，`contract:check` 在 CI 阻止漂移。

Registry 工具、API 与 Web manifest builder 直接复用 TypeScript `ManifestValidator`；
不再各写一份校验规则。Python 与 TypeScript 还共同消费 `spec/conformance/vectors/*.yaml`，
覆盖坐标、digest、缓存布局、manifest、registry 和 ordered fallback。

## `publish` 签名（01 实施时定，无先例可循）

发布与取回是同一个驱动的两面，因此 `publish` 放在 `Source` 的可选扩展协议
`PublishingSource` 上，而不是另起一套 uploader 体系。

```python
def publish(self, files: Sequence[Path], target: str,
            publication: Publication) -> Locator: ...
```

三个决定及其理由：

1. **返回 `Locator` 而不是 URL 或平台原始响应。** 这样发布产出的东西可以直接
   填进 manifest 的 `locators` 数组——发布和取回闭环，而不是两个互不相干的功能。
2. **元数据用冻结值对象 `Publication`，不用裸 dict。** CLAUDE.md 禁 god data。
   字段只保留三个平台都有对应物的那些（title / description / license /
   keywords / private）；平台特有的东西留在该驱动自己的方法里，不塞进公共包。
   每个驱动的 docstring 写明它表达不了哪些字段（如 Figshare 无法表达 private）。
3. **`target` 是平台自己的话语。** HF 是 `org/repo`，Figshare 是 article id 或
   字面量 `"new"`。与 `Locator.path` 对驱动不透明是同一个原则——molhub 不试图
   统一各平台的容器概念。

凭据只在发布时索取：`resolve` 是匿名的，token 缺失要到真正 publish 时才报错。
`molhub.uploader` 降级为 shim，保两个小版本。

## 版本标识靠 DOI 与钉版本的 locator，不靠 digest

**manifest 规定的是数据集的哪一版。** 让"哪一版"精确的是 **locator 必须钉住上游
理解的版本**，以及记下该版本的 **DOI**——持久标识符本来就是干这个的，不需要
molhub 另造一套身份。

**踩过的坑**：`figshare://1057646` 解析到的是"当前版"。article 1057646 已经有
v1 和 v2；上游哪天发 v3，这份 manifest 就开始供应 v3，且毫无迹象。必须写成
`figshare://1057646/v2/<file>`。有一条测试遍历内置 registry，禁止出现不钉版本的
Figshare locator。

各平台的版本表达：

| 平台 | 版本怎么钉 |
|---|---|
| Zenodo | record id 本身就是版本；另有 concept DOI 指向"最新" |
| Figshare | article id **不**分版本，必须带 `/v<n>`；每个 article 有自己的 DOI |
| HuggingFace | commit SHA（locator 里写 `repo@<rev>`） |

**digest 是次要的交叉检查，可选。** 上游公布什么就照抄什么（Figshare/Zenodo 是
md5，HF 是 sha256 LFS OID），不公布就不记。它防的是平台违背自己的不可变承诺，
不是版本标识的主力。

**molhub 绝不自行计算 digest。** 曾经的设计是「sha256 必填、由 molhub 取回后
算出」，两个后果都很糟：自算的值只能证明"我那次下载到了什么"；而且写一份 manifest
要先把整个制品下载一遍——revMD17 十个分子就要 1.2 GB 才能写出十个 YAML。
**目录不该需要先把货搬一遍才能编目。**

**但每个 artifact 至少要有一项交叉检查：`digest` 或 `size`，两者取一。** 两个都
不填，一次"完成"的传输就没有任何东西可以比对。这条不要求 digest 是有意的——不公布
digest 的平台确实存在（3BPA 挂在 GitHub raw，只有 commit 钉版本，无内容校验和），
而 `size` 一个 HEAD 请求就能拿到 content-length，不搬货，与上一段的原则不冲突。
schema 用 `anyOf: [{required: [digest]}, {required: [size]}]` 表达，Python 解析器
同步拒绝，两侧必须一致。

**`size` 必须 ≥ 1。** `size: 0` 会同时满足上面那条「二选一」规则却什么也校验不了：
零不是更小的制品，是传输失败的形状。本仓的事故原型正是 Figshare 返回 202 + 空 body
被当成合法排除表缓存。而 size 可能是一个 artifact 唯一的交叉检查，放行 0 就等于
把那次线上的失败原样搬进目录层。schema 用 `exclusiveMinimum: 0`，解析器同步拒绝。

> **以上两次收紧都没有升 `schema_version`，是有意识的判断，不是先例。**
> 收紧本属破坏性变更。豁免的唯一理由是此刻契约还没有任何外部生产者——
> `molhub-registry` 仓刚建立且尚未发布，TS 客户端尚未动工，内置 registry 的 18 个 artifact
> 全部已合规。**registry 仓一旦公开接受外部 PR，这个窗口就关闭**，之后任何收紧都必须
> 升版本。

**传输正确性与以上全部无关。** 202、半截、错误响应由传输契约拦住（查 status →
流式写临时文件 → 原子改名）。

缓存因此也不需要内容寻址：按 manifest 已给出的坐标 + role 存放
（`$MOLHUB_HOME/files/<kind>/<ns>/<name>@<ver>/<role>`）。
