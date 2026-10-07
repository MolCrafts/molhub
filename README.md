<div align="center">

<h1>
  <img src=".github/assets/moko.svg" alt="" height="48" align="absmiddle">
  &nbsp;molhub
</h1>

<p><strong>Unified access to molecular benchmark datasets, with one-click upload to public data repositories.</strong></p>

<p>
  <a href="https://github.com/MolCrafts/molhub/actions/workflows/test.yml"><img src="https://img.shields.io/github/actions/workflow/status/MolCrafts/molhub/test.yml?style=flat-square&logo=githubactions&logoColor=white&label=test" alt="test"></a>
  <img src="https://img.shields.io/badge/license-BSD--3--Clause-18432B?style=flat-square" alt="License">
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square" alt="Ruff"></a>
</p>

<p>
  <a href="#quick-start"><b>Quick start</b></a> &nbsp;&middot;&nbsp;
  <a href="#molcrafts-ecosystem"><b>Ecosystem</b></a>
</p>

</div>

molhub gives molecular datasets, models, and plugins one stable name and one way to get them. A coordinate like `dataset:molcrafts/polymer-tg@1` resolves through a registry of YAML manifests to an ordered list of mirrors. Adding an artifact is a manifest, not a release.

What guarantees the bytes are usable is the **transport contract**: check the response status, stream to a temporary file, rename into place atomically. A truncated body or a `202 Accepted` placeholder never lands on the final path. What pins *which version* you get is the **locator**, which must name a version upstream understands — a Figshare article version, a Zenodo record id, a git commit — together with the **DOI** the manifest records beside it. A `digest` is optional and secondary: molhub copies whatever the platform publishes, verbatim and in whatever algorithm it publishes it (md5 for QM9 and revMD17; nothing at all for 3BPA, because GitHub publishes no content checksum for a blob). When present it is checked, and what it proves is that upstream still serves the version the manifest names. molhub never computes a digest of its own.

On top of that, `molhub.dataset` gives every dataset the same interface — index by position, iterate sample by sample, or slice with subsets — so downstream code works identically across QM9, revMD17, 3BPA, or your own CSV files.

> **Under active development.** Public APIs may change between minor releases.

## Repository boundaries

This repository owns the MolHub product, its shared contract, and every runtime.
`apps/` contains independently deployable applications; `packages/` contains
reusable Node packages; the Python package keeps its conventional `src/`
layout. Approved records remain in a separate data-only repository.

| Boundary | Location | Owns |
|---|---|---|
| Python SDK | `src/molhub/`, `tests/` | Local resolve, search, fetch, cache, publishing, and dataset protocols |
| TypeScript SDK | `packages/typescript/` | Browser resolve/search plus Node resolve/search/fetch and CLI |
| Product Web | `apps/web/` | Discovery, artifact details, MolVis/MolPlot Inspector, and direct manifest submission |
| Submission API | `apps/api/` | D1-backed submission state, review, GitHub PR publication, and merge webhooks |
| Shared contract | `spec/` | The only hand-authored manifest and registry schemas plus cross-language vectors |
| Registry tooling | `packages/registry-tools/` | Validation and deterministic snapshot generation |
| Registry database | [`MolCrafts/molhub-registry`](https://github.com/MolCrafts/molhub-registry) | Approved YAML manifests only |
| Scientific payloads | Zenodo, Figshare, Hugging Face, git hosts | The actual artifact bytes |

The Web build uses the shared registry builder to derive `registry.json` from a
sibling database, or accepts an explicit snapshot through
`MOLHUB_REGISTRY_JSON`. The Web never writes approved manifests.

## Product development

Use Node 22 and run commands from this repository root:

```bash
npm install
npm run dev --workspace @molcrafts/molhub-web   # http://localhost:4173/molhub/
```

For direct website submission, start the D1-backed API in another terminal:

```bash
cp apps/api/.dev.vars.example apps/api/.dev.vars
npm run db:migrate:local --workspace @molcrafts/molhub-api
npm run dev --workspace @molcrafts/molhub-api   # http://localhost:8787
```

Keep `molhub-registry` checked out beside this repository, or set
`MOLHUB_REGISTRY_JSON` to an explicit generated snapshot. See
[`apps/web/README.md`](apps/web/README.md) and
[`apps/api/README.md`](apps/api/README.md).

## Capabilities

| Layer | Module | Capability |
|-------|--------|------------|
| Addressing | `Coordinate` | The stable name `kind:namespace/name@version`, with `qm9@v2` as shorthand for `dataset:molcrafts/qm9@v2`. A version is mandatory — molhub never resolves "latest" |
| Registry | `Registry`, `Manifest` | YAML manifests carry title, license, DOI, declared targets, and one entry per downloadable file. A bundled snapshot ships in the package; `$MOLHUB_REGISTRY` points at a directory of your own |
| Transport | `Fetcher` | Tries an artifact's locators in order and takes the first that yields a complete `200`; status check → temp file → atomic rename, plus the optional digest cross-check |
| Transport | `BlobStore` | On-disk cache keyed by coordinate and role under `$MOLHUB_HOME`, reserved as a cross-SDK contract so one machine downloads once |
| Transport | `Source` drivers | `https`, `zenodo`, `figshare`, `hf`, `molhub` out of the box. A third party adds a scheme by publishing a driver to the `molhub.sources` entry point — no molhub source change. `PublishingSource` adds upload to the same driver |
| CLI | `molhub` | `search`, `info`, `fetch --into`, `cache verify` — the same verbs as the Python API |
| Datasets | `molhub.dataset` (protocols) | `MapDataset` and `IterableDataset` runtime-checkable protocols, plus `TargetSchema` declaring graph-level vs atom-level targets |
| Datasets | `molhub.dataset` (helpers) | `InMemoryDataset` wraps a list of frames; `SubsetDataset` slices any map-style dataset by index |
| Datasets | `QM9Dataset` | 130,831 small organic molecules with quantum-chemical properties — auto-downloads & caches `dataset:molcrafts/qm9@v2` |
| Datasets | `RevMD17Dataset` | Revised MD17 trajectories for 10 molecules, with energies and forces — auto-downloads & caches one molecule of `dataset:molcrafts/revmd17@v4` |
| Datasets | `ThreeBPADataset` | 3BPA temperature-transferability benchmark at 300 K / 600 K / 1200 K — auto-downloads & caches one split of `dataset:molcrafts/3bpa@v1` |
| Datasets | `CSVDataset` | Generic CSV loader for local files or remote URLs — zero extra dependencies, each row becomes a `Frame` |
| Publishing | `PublishingSource` | The write half of a driver: `publish(files, target, publication)` returns the `Locator` that goes straight into a manifest. Implemented by the Figshare and HuggingFace drivers |
| Publishing | `molhub.uploader` | Deprecated shims (`HuggingFaceUploader`, `FigshareUploader`) forwarding to those drivers, kept for existing callers |
| Inspector | `apps/web/` | Shareable structure/trajectory and property-map exploration, with original-source provenance |

Each sample is a [molpy](https://github.com/MolCrafts/molpy) `Frame`: the `atoms` block holds per-atom data (`element`, `x`, `y`, `z`, `number`, and optionally `fx`, `fy`, `fz`), while graph-level targets such as energy live in `frame.meta`. molpy stores those as dtype-tagged `MetaValue` entries — use `molhub.dataset.Targets(frame)` to read them back as plain Python values.

## Install

```bash
pip install molhub                 # core: source, registry, CLI, dataset sources, Figshare publishing
pip install molhub[huggingface]    # + HuggingFace Hub upload support
pip install molhub[dev]            # + dev tooling (pytest, pytest-cov, pytest-mock, ruff, ty, jsonschema, tox)
```

Requires Python >= 3.12. Core dependencies: `molcrafts-molpy >= 0.12, < 0.13`, `tqdm`, `requests >= 2.28`, `pyyaml >= 6.0`, `typer >= 0.12`. Installing the package also puts a `molhub` command on your `PATH`.

## Quick start

```python
from molhub import Molhub

hub = Molhub()

# Resolution and search read the bundled registry — no network.
info = hub.resolve("polymer-tg@1")     # shorthand for dataset:molcrafts/polymer-tg@1
print(info.title, info.license, info.doi)
# LAMALAB curated polymer glass-transition temperatures CC-BY-4.0 10.5281/zenodo.14980914
print(info.artifact("main").digest)    # md5:ce2c7b2a879450cbbfff4d7ccea648f9 — Zenodo's own value
for locator in info.artifact("main").locators:
    print(locator)                     # zenodo://14980914/LAMALAB_CURATED_Tg_structured.csv

for manifest in hub.search(query="polymer"):
    print(manifest.coordinate.canonical, "—", manifest.title)
# dataset:molcrafts/polymer-tg@1 — LAMALAB curated polymer glass-transition temperatures

# Fetching hits the network on the first call only. Not run here.
paths = hub.fetch("dataset:molcrafts/polymer-tg@1")
# {'main': PosixPath('/home/you/.cache/molhub/files/dataset/molcrafts/polymer-tg@1/main')}
```

Files are cached at `$MOLHUB_HOME/files/<kind>/<namespace>/<name>@<version>/<role>` (default root `~/.cache/molhub`) — a path built from the coordinate and the role, **not** a content hash. That is deliberate: the manifest already names the file, so no digest has to be invented for the platforms that publish none. A cached file is returned without any network access, and the layout is a cross-SDK contract.

From the shell:

```bash
molhub search polymer
molhub info dataset:molcrafts/polymer-tg@1
molhub fetch polymer-tg@1 --into ./data
molhub cache verify            # re-check cached files against their manifests' digests;
                               # files whose manifest declares none are counted and skipped
```

### Adding a source

A hosting platform is a `Source` driver: a `scheme` plus `resolve` and `fetch`. Nothing else in molhub knows the difference, including MolCrafts' own source.

```python
from pathlib import Path

from molhub import Molhub
from molhub.sources import Drivers, Fetcher, Locator, RemoteFile

class MySource:
    scheme = "mine"

    def resolve(self, locator: Locator) -> list[RemoteFile]:
        return [RemoteFile(url=f"https://example.org/{locator.path}", filename="data.csv")]

    def fetch(self, remote: RemoteFile, dest: Path) -> Path:
        ...   # must check status, stream, and leave nothing at dest on failure

hub = Molhub(fetcher=Fetcher(drivers=Drivers.discover().with_driver(MySource())))
```

An installed package can register a driver through the `molhub.sources` entry-point group instead, and `Drivers.discover()` picks it up with no code change on either side.

### Using your own registry

The registry is a directory of YAML manifests laid out as `<kind>/<namespace>/<name>/<version>.yaml`, with no service behind it. molhub reads `$MOLHUB_REGISTRY` if set, otherwise the snapshot bundled in the package — which is why a fresh install resolves the built-in datasets offline.

```python
from molhub import Molhub

hub = Molhub("./my-registry")        # or export MOLHUB_REGISTRY=./my-registry
print(len(hub))                   # number of manifests loaded
```

A malformed manifest raises `InvalidManifest` at load time rather than being skipped: a silently dropped dataset is worse than a loud registry. `spec/manifest.schema.yaml` is the source of truth; `npm run contract:sync` generates the Python and TypeScript runtime copies consumed by every validation surface.

Two rules bite when you write a manifest by hand:

- **Every locator must pin a version upstream understands.** A Figshare article id alone follows whatever becomes current, so write `figshare://<id>/v<n>/<file>`. A Zenodo record id already is a version. A HuggingFace locator without `@<rev>` resolves to `main`, so write `hf://<org>/<repo>@<commit>/<file>`. A plain URL to a git host needs a commit id, never a branch name. Record the version's `doi` alongside.
- **Every artifact needs a `digest` or a `size`, or both.** Copy whatever checksum the platform publishes — molhub never computes one, because a self-computed digest attests only to your own download, and requiring one would mean fetching an artifact before you could list it. When the platform publishes no checksum, a `size` from a `HEAD` request's `content-length` is the accepted answer.

### Dataset sources

Every built-in source resolves its own coordinate and fetches through `Molhub`, so there is nothing to download by hand. The blocks below reach upstream on a cold cache.

```python
from molhub.dataset import QM9Dataset, CSVDataset, Targets

# Load QM9 — auto-downloads & caches dataset:molcrafts/qm9@v2
qm9 = QM9Dataset("./data/qm9")
print(len(qm9))          # 130831
frame = qm9[42]          # one sample carries atoms + computed properties
print(Targets(frame).read())   # {'A': ..., 'B': ..., 'U0': ..., ...}

# Load any CSV from a URL or local file. A bare URL is not a coordinate: there is
# no manifest and no published digest behind it, so it is cached by name under
# $MOLHUB_HOME/urls/ instead.
ds = CSVDataset("https://zenodo.org/records/14980914/files/LAMALAB_CURATED_Tg_structured.csv")
print(ds.headers)        # ['labels.SMILES', 'labels.Exp_Tg(K)', ...] (column names as published)
frame = ds[0]
print(Targets(frame)["labels.Exp_Tg(K)"])
```

### Dataset protocols

Every dataset conforms to one of two runtime-checkable protocols, so downstream code can consume them generically.

`MapDataset` — index-addressable; supports `len()` and random access by integer position. Use when samples fit in memory or are backed by a random-access store.

```python
from molpy import Frame

from molhub.dataset import MapDataset

class MyDataset:
    def __len__(self) -> int: ...
    def __getitem__(self, idx: int) -> Frame: ...
    @property
    def source_id(self) -> str: ...

assert isinstance(MyDataset(), MapDataset)  # runtime-checkable protocol
```

`IterableDataset` — streaming; samples are yielded one at a time. Use for lazy file readers, on-the-fly generation, or datasets too large to hold in memory.

```python
from typing import Iterator

from molpy import Frame

from molhub.dataset import IterableDataset

class MyStream:
    def __iter__(self) -> Iterator[Frame]: ...
    @property
    def source_id(self) -> str: ...

assert isinstance(MyStream(), IterableDataset)
```

`TargetSchema` — each dataset declares where its targets live, so batching and collation logic knows what to expect:

| Target level | Location | Example |
|---|---|---|
| `graph_level` | `frame.meta` (read via `Targets(frame)`) | `energy`, `homo`, `lumo` |
| `atom_level` | `atoms` block columns | `fx`, `fy`, `fz` |

`InMemoryDataset` / `SubsetDataset` — convenience helpers for wrapping and slicing:

```python
from molhub.dataset import InMemoryDataset, SubsetDataset

inmem = InMemoryDataset(frames, name="my-frames")        # wrap a list
subset = SubsetDataset(inmem, indices=[0, 10, 100])      # slice by index

print(inmem.source_id)    # memory:my-frames:<len>
print(subset.source_id)   # memory:my-frames:<len>:subset=<12-hex-chars>
```

`source_id` identifies one *view* of the data, and it is what a downstream cache keys on. A built-in source that reads an artifact unmodified reports its coordinate verbatim; anything narrower appends qualifiers after a `#`, which is deliberately not coordinate syntax — `dataset:molcrafts/revmd17@v4#molecule=aspirin` names a view, not an artifact. `CSVDataset` reports `csv:<filename>:n=<rows>`, since a raw path or URL has no coordinate at all.

### Built-in datasets

**QM9** (`QM9Dataset`) — `dataset:molcrafts/qm9@v2`, 130,831 small organic molecules with quantum-chemical properties. Two roles: `main` (the tarball) and `exclude` (the uncharacterized list that brings 133,885 records down to 130,831). Reference: Ramakrishnan et al., *Scientific Data* 1, 140022 (2014).

```python
from molhub.dataset import QM9Dataset

source = QM9Dataset("./data/qm9", targets=["U0", "H", "gap"])
# Auto-downloads & caches both roles, then lazy-loads on first access.
print(source.source_id)   # dataset:molcrafts/qm9@v2#targets=H+U0+gap

# Offline: pass download=False and put qm9.tar.bz2 + qm9_exclude.txt in root.
```

Graph-level targets: `A`, `B`, `C`, `mu`, `alpha`, `homo`, `lumo`, `gap`, `r2`, `zpve`, `U0`, `U`, `H`, `G`, `Cv`.

**revMD17** (`RevMD17Dataset`) — `dataset:molcrafts/revmd17@v4`, MD17 trajectories recomputed at PBE/def2-SVP for 10 molecules. Upstream publishes each molecule as its own file, so the manifest declares **one role per molecule** (plus a `readme`) and a source fetches only the one it needs — about 150 MB rather than the 1 GB archive. Reference: Christensen & von Lilienfeld, *MLST* (2020).

```python
from molhub.dataset import RevMD17Dataset, Targets

source = RevMD17Dataset("./data/revmd17", molecule="aspirin")
# Auto-downloads & caches role "aspirin" of dataset:molcrafts/revmd17@v4.
print(source.source_id)   # dataset:molcrafts/revmd17@v4#molecule=aspirin

frame = source[100]
# atoms block: element, x, y, z, number, fx, fy, fz
print(Targets(frame).read())   # {'energy': ...}

# Offline: pass download=False and put rmd17_aspirin.npz in root.
```

Available molecules: `aspirin`, `azobenzene`, `benzene`, `ethanol`, `malonaldehyde`, `naphthalene`, `paracetamol`, `salicylic`, `toluene`, `uracil`. Coordinates are in ångström, energies in kcal/mol, forces in kcal/(mol·Å).

**3BPA** (`ThreeBPADataset`) — `dataset:molcrafts/3bpa@v1`, the temperature-transferability benchmark. The manifest declares **four roles**, one per extended-XYZ file: `train_300K`, `test_300K`, `test_600K`, `test_1200K`. Its locators pin a GitHub commit rather than a branch; GitHub publishes no content checksum, so these entries carry no `digest` and the commit pin is what fixes the bytes. Reference: Kovacs et al., *J. Chem. Theory Comput.* (2021).

```python
from molhub.dataset import ThreeBPADataset

# Nothing usable at the given path -> the split named by `tag` is fetched and cached.
train = ThreeBPADataset("train_300K.xyz", tag="train_300K")
print(train.source_id)    # dataset:molcrafts/3bpa@v1#split=train_300K

# A real file at the path is parsed as-is and nothing is fetched.
test_600 = ThreeBPADataset("./data/3bpa/test_600K.xyz", tag="test_600K")

print(sorted(ThreeBPADataset.SPLITS))
# ['test_1200K', 'test_300K', 'test_600K', 'train_300K']
```

Energies are in eV and forces in eV/Å, as distributed.

**CSVDataset** — generic CSV loader, works on local files and remote URLs. No extra dependencies.

```python
from molhub.dataset import CSVDataset

ds = CSVDataset("/path/to/data.csv")
ds = CSVDataset("https://example.com/data.csv")
# cached to $MOLHUB_HOME/urls/, falling back to ~/.cache/molhub/urls/
# ($MOLHUB_CACHE_DIR still works but is deprecated: read only when $MOLHUB_HOME is unset)
```

### Publishing

Publishing and fetching are two halves of one driver: a `Source` that also implements `PublishingSource` accepts uploads and returns a `Locator` — exactly the string that goes into a manifest's `locators`, so the loop closes.

```python
from pathlib import Path

from molhub.sources import Drivers, Publication

figshare = Drivers.discover().for_scheme("figshare")   # needs $FIGSHARE_TOKEN
locator = figshare.publish(
    [Path("data/qm9.tar.bz2")],
    "new",                                             # or an existing article id
    Publication(title="QM9 dataset", license="CC0-1.0", keywords=("quantum-chemistry",)),
)
print(locator)   # paste into the manifest's `locators` list
```

`target` is spelled in the platform's own terms: a HuggingFace `org/repo`, a Figshare article id, or the literal `"new"` where the platform can mint a container. Each driver documents which `Publication` fields it cannot express.

#### Uploader shims (deprecated)

`molhub.uploader` predates the driver protocol and now forwards to it. It is kept so existing callers keep working and is scheduled for removal two minor releases after 0.1 — prefer `publish` above.

**HuggingFace Hub** — requires `pip install molhub[huggingface]`.

```python
from molhub.uploader import HuggingFaceUploader

uploader = HuggingFaceUploader(token="hf_...")  # or set HF_TOKEN

uploader.upload_file("data/qm9.tar.bz2", repo_id="my-org/qm9", path_in_repo="raw/qm9.tar.bz2")
uploader.upload_folder("data/processed/", repo_id="my-org/dataset", path_in_repo="processed/")
uploader.upload_dataset("data/dataset.h5", repo_id="my-org/new-dataset")  # create + upload
```

**Figshare** — uses the core `requests` dependency; no extra install needed.

```python
from molhub.uploader import FigshareUploader

uploader = FigshareUploader(token="...")  # or set FIGSHARE_TOKEN

result = uploader.upload_dataset(
    "data/qm9.tar.bz2",
    title="QM9 dataset",
    description="Raw QM9 molecular properties dataset",
    tags=["quantum-chemistry", "molecules"],
)
print(result["article"]["id"], result["file"])
```

## MolCrafts ecosystem

| Project | Role |
|---------|------|
| [molpy](https://github.com/MolCrafts/molpy)     | Python toolkit — the shared molecular data model & workflow layer |
| [molrs](https://github.com/MolCrafts/molrs)     | Rust core — molecular data structures & compute kernels (native + WASM) |
| [molpack](https://github.com/MolCrafts/molpack) | Packmol-grade molecular packing (Rust + Python) |
| [molvis](https://github.com/MolCrafts/molvis)   | WebGL molecular visualization & editing |
| [molexp](https://github.com/MolCrafts/molexp)   | Workflow & experiment-management platform |
| [molnex](https://github.com/MolCrafts/molnex)   | Molecular machine-learning framework |
| [molq](https://github.com/MolCrafts/molq)       | Unified job queue — local / SLURM / PBS / LSF |
| [molcfg](https://github.com/MolCrafts/molcfg)   | Layered configuration library |
| [mollog](https://github.com/MolCrafts/mollog)   | Structured logging, stdlib-compatible |
| **molhub**                                      | **Molecular dataset hub — this repo** |
| [molmcp](https://github.com/MolCrafts/molmcp)   | MCP server for the ecosystem |
| [molrec](https://github.com/MolCrafts/molrec)   | Atomistic record specification |

## License

BSD-3-Clause — see [LICENSE](LICENSE).

<hr>

<div align="center">
<sub>Crafted with 💚 by <a href="https://github.com/MolCrafts">MolCrafts</a></sub>
</div>
