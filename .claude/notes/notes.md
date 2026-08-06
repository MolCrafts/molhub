# 项目决策记录

由 `/mol:note` 维护。**同步式**：规则变了就改写/删除旧条目，不是只追加。

---

## 定位：目录 + 归一化，不做字节仓储

molhub 不托管大制品字节。分子数据集体量大（GB~TB）、再分发授权复杂，
自建存储既不划算也不合规。molhub 的价值在**归一化与可寻址**：任何来源的东西
都能通过一个稳定坐标取到、并被强制校验。字节留在上游（Zenodo / Figshare /
HuggingFace）。

**例外**：MolCrafts 自家插件走自建的小型 registry（静态对象存储 + CDN）。
它必须实现同一套 `Registry` 接口，**不得特例化**——如果它需要开后门，
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

由此立为硬规则：manifest 中 digest 必填，CI 拒绝无 digest 的条目；digest 由
bot 从上游 API 自动抓取，不手写；fetch 契约为「查 status → 流式写临时文件 →
校验 digest → 原子改名」，任一步失败即换下一个 locator。

**已落地**（2026-08-06）：`molhub.registry` 承担全部传输，五步 fetch 契约与
digest 强校验由 `HttpsRegistry` + `Fetcher` 实现，回归测试锁定 202、digest 不符、
传输中断三条失败路径。数据源的两处 `_download` 已删除，统一走 `DownloadCache`。
数据源本身尚未用 `Fetcher`——那要等 02 给它们 manifest digest。

## molpy 版本策略：小版本会搬公开 API

molpy 是 pre-1.0，且在小版本间移动公开 API。0.3 → 0.9 把 `Frame`/`Block`/
`Element` 从 `molpy.core.*` 搬到顶层，并把 `Frame.metadata` 改名 `Frame.meta`。
原先 `molcrafts-molpy>=0.3.0` 的开放下界让这次破坏性升级悄悄进了 lock，
origin/master 一度不可导入且 CI 未覆盖。依赖已收紧为 `>=0.12,<0.13`。

**0.12 的 metadata 契约有两个静默陷阱**，全部封装在 `molhub.dataset.meta`：

1. `Frame.meta` 每次读取返回**新 dict**，原地 `update`/`clear` 写进临时对象后被
   丢弃，**不报错**。必须整体赋值 `frame.meta = {...}`。
2. 值必须是 `MetaValue(dtype, value)`，裸 Python 值被拒；dtype 字符串是
   `f64/f32/i64/i32/u64/bool/string`——字符串标签是 `string` 而非 `str`。

调用方一律走 `Targets(frame).write({...})` / `.read()`，不直接碰 `MetaValue`。
`MetaCodec` 单独承担值↔`MetaValue` 的编解码，可注入替换。`test_meta.py` 里有一条回归测试专门锁定陷阱 1：若 molpy 哪天改成
可原地修改，那条测试会失败，届时可重新评估这层封装。

另注：`len(Block)` 是**列数**，行数是 `Block.nrows`；`len(Frame)` 是 block 个数。

## 多语言绑定：规格先行

Python 与 TypeScript 两套客户端**必然漂移**，且靠 code review 兜不住。对策：

- JSON Schema（以 YAML 书写）定义 manifest / index / 坐标语法，置于索引仓
- **语言中立的 conformance 测试套件**（YAML 测试向量 + mock registry），
  两端必须同时通过：坐标解析、locator fallback 顺序、digest 校验失败路径、缓存布局
- 缓存磁盘布局写入规格，两端同机共享 `$MOLHUB_HOME` 互相命中
- `schema_version` 版本化

## 索引独立成仓

manifest 放在独立的 `molhub-index` 仓，不放客户端仓。理由：外部贡献者提
manifest 不应需要客户端仓写权限，也不应触发库发版。`qm9.py` 仍把上游 URL 硬编码成 Python 常量——改一个链接要发一次版，
这正是 02 要消除的形态。

## `publish` 签名（01 实施时定，无先例可循）

发布与取回是同一个驱动的两面，因此 `publish` 放在 `Registry` 的可选扩展协议
`PublishingRegistry` 上，而不是另起一套 uploader 体系。

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
`figshare://1057646/v2/<file>`。有一条测试遍历内置索引，禁止出现不钉版本的
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

**传输正确性与以上全部无关。** 202、半截、错误响应由传输契约拦住（查 status →
流式写临时文件 → 原子改名）。

缓存因此也不需要内容寻址：按 manifest 已给出的坐标 + role 存放
（`$MOLHUB_HOME/files/<kind>/<ns>/<name>@<ver>/<role>`）。
