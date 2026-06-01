<div align="center">

<h1>
  <img src=".github/assets/moko.svg" alt="" height="48" align="absmiddle">
  &nbsp;molhub
</h1>

<p><strong>Unified access to molecular benchmark datasets, with one-click upload to public data repositories.</strong></p>

<p>
  <a href="https://github.com/MolCrafts/molhub/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/MolCrafts/molhub/ci.yml?style=flat-square&logo=githubactions&logoColor=white&label=CI" alt="CI"></a>
  <img src="https://img.shields.io/badge/license-BSD--3--Clause-18432B?style=flat-square" alt="License">
  <a href="https://github.com/astral-sh/ruff"><img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square" alt="Ruff"></a>
</p>

<p>
  <a href="#quick-start"><b>Quick start</b></a> &nbsp;&middot;&nbsp;
  <a href="#molcrafts-ecosystem"><b>Ecosystem</b></a>
</p>

</div>

molhub gives every molecular dataset the same interface — index by position, iterate sample by sample, or slice with subsets — and ships uploaders for publishing your own data to HuggingFace Hub and Figshare. Samples carry atomic coordinates, forces, and computed properties in a consistent structure, so downstream code works identically across QM9, revMD17, 3BPA, or your own CSV files.

> **Under active development.** Public APIs may change between minor releases.

## Capabilities

| Module | Capability |
|--------|------------|
| `molhub.dataset` (protocols) | `MapDataset` and `IterableDataset` runtime-checkable protocols, plus `TargetSchema` declaring graph-level vs atom-level targets |
| `molhub.dataset` (helpers) | `InMemoryDataset` wraps a list of frames; `SubsetDataset` slices any map-style dataset by index |
| `QM9Source` | 130,831 small organic molecules with quantum-chemical properties — auto-downloads & caches from Figshare |
| `RevMD17Source` | Revised MD17 molecular-dynamics trajectories for 10 molecules, with energies and forces |
| `ThreeBPASource` | 3BPA temperature-transferability benchmark — extended-XYZ files at 300 K / 600 K / 1200 K |
| `CSVDataset` | Generic CSV loader for local files or remote URLs — zero extra dependencies, each row becomes a `Frame` |
| `HuggingFaceUploader` | Upload files, folders, and datasets to a HuggingFace Hub repository |
| `FigshareUploader` | Create Figshare articles and upload files via the Figshare REST API |

Each sample is a [molpy](https://github.com/MolCrafts/molpy) `Frame`: the `atoms` block holds per-atom data (`element`, `x`, `y`, `z`, `number`, and optionally `fx`, `fy`, `fz`), while graph-level targets such as energy live in `frame.metadata`.

## Install

```bash
pip install molhub                 # core (datasets + protocols + Figshare uploader)
pip install molhub[huggingface]    # + HuggingFace Hub upload support
pip install molhub[dev]            # + dev tooling (pytest, pytest-cov, pytest-mock, ruff)
```

Requires Python >= 3.10. Core dependencies: `molcrafts-molpy >= 0.3.0`, `tqdm`, `requests >= 2.28`.

## Quick start

```python
from molhub.dataset import QM9Source, CSVDataset

# Load QM9 — auto-downloads & caches the 130k-molecule tarball
qm9 = QM9Source("./data/qm9")
print(len(qm9))          # 130831
frame = qm9[42]          # one sample carries atoms + computed properties
print(frame.metadata)    # {'A': ..., 'B': ..., 'U0': ..., ...}

# Load any CSV from a URL or local file
ds = CSVDataset("https://zenodo.org/records/14980914/files/LAMALAB_CURATED_Tg_structured.csv")
print(ds.headers)        # ['labels.SMILES', 'labels.Exp_Tg(K)', ...]
frame = ds[0]
print(frame.metadata["labels.Exp_Tg(K)"])  # 373.0
```

### Dataset protocols

Every dataset conforms to one of two runtime-checkable protocols, so downstream code can consume them generically.

`MapDataset` — index-addressable; supports `len()` and random access by integer position. Use when samples fit in memory or are backed by a random-access store.

```python
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
| `graph_level` | `frame.metadata` | `energy`, `homo`, `lumo` |
| `atom_level` | `atoms` block columns | `fx`, `fy`, `fz` |

`InMemoryDataset` / `SubsetDataset` — convenience helpers for wrapping and slicing:

```python
from molhub.dataset import InMemoryDataset, SubsetDataset

inmem = InMemoryDataset(frames, name="my-frames")        # wrap a list
subset = SubsetDataset(qm9, indices=[0, 10, 100, 1000])  # slice by index
```

### Built-in datasets

**QM9** (`QM9Source`) — 130,831 small organic molecules with quantum-chemical properties. Reference: Ramakrishnan et al., *Scientific Data* 1, 140022 (2014).

```python
from molhub.dataset import QM9Source

source = QM9Source("./data/qm9", targets=["U0", "H", "gap"])
# Auto-downloads from Figshare, caches locally, lazy-loads on first access
```

Graph-level targets: `A`, `B`, `C`, `mu`, `alpha`, `homo`, `lumo`, `gap`, `r2`, `zpve`, `U0`, `U`, `H`, `G`, `Cv`.

**revMD17** (`RevMD17Source`) — revised MD17 molecular-dynamics trajectories (10 molecules). Reference: Christensen & von Lilienfeld, *MLST* (2020).

```python
from molhub.dataset import RevMD17Source

source = RevMD17Source("./data/revmd17", molecule="aspirin")
frame = source[100]
# atoms block: element, x, y, z, number, fx, fy, fz
# metadata: {'energy': ...}
```

Available molecules: `aspirin`, `azobenzene`, `benzene`, `ethanol`, `malonaldehyde`, `naphthalene`, `paracetamol`, `salicylic`, `toluene`, `uracil`.

**3BPA** (`ThreeBPASource`) — temperature-transferability benchmark at 300 K, 600 K, and 1200 K. Reference: Kovacs et al., *J. Chem. Theory Comput.* (2021).

```python
from molhub.dataset import ThreeBPASource

train = ThreeBPASource("./data/3bpa/train_300K.xyz", tag="train_300K")
test_600 = ThreeBPASource("./data/3bpa/test_600K.xyz", tag="test_600K")
```

**CSVDataset** — generic CSV loader, works on local files and remote URLs. No extra dependencies.

```python
from molhub.dataset import CSVDataset

ds = CSVDataset("/path/to/data.csv")
ds = CSVDataset("https://example.com/data.csv")
# cached to $MOLHUB_CACHE_DIR, falling back to ~/.cache/molhub
```

### Uploaders

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
