# MolHub

**Molecular dataset hub** — unified access to molecular benchmark datasets and one-click upload to public data repositories.

Every dataset speaks the same interface: index by position, iterate sample by sample, or slice with subsets. Samples carry atomic coordinates, forces, and computed properties in a consistent structure, so downstream code works identically across QM9, revMD17, 3BPA, or your own CSV files.

## Installation

```bash
pip install molhub                    # core (datasets + protocols)
pip install molhub[huggingface]       # + HuggingFace Hub upload support
pip install molhub[figshare]          # + Figshare upload support
pip install molhub[dev]               # + dev tooling (pytest, ruff, pytest-cov)
pip install molhub[huggingface,figshare,dev]  # everything
```

**Requirements:** Python >= 3.10, `molcrafts-molpy >= 0.3.0`.

## Quickstart

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

## Dataset Protocols

Every dataset conforms to one of two protocols so downstream code can consume them generically.

### `MapDataset`

Index-addressable — supports `len()` and random access by integer position. Use when samples fit in memory or are backed by a random-access store.

```python
from molhub.dataset import MapDataset

class MyDataset:
    def __len__(self) -> int: ...
    def __getitem__(self, idx: int) -> Frame: ...
    @property
    def source_id(self) -> str: ...

assert isinstance(MyDataset(), MapDataset)  # runtime-checkable protocol
```

### `IterableDataset`

Streaming — samples are yielded one at a time. Use for lazy file readers, on-the-fly generation, or datasets too large to hold in memory.

```python
from molhub.dataset import IterableDataset

class MyStream:
    def __iter__(self) -> Iterator[Frame]: ...
    @property
    def source_id(self) -> str: ...

assert isinstance(MyStream(), IterableDataset)
```

### `TargetSchema`

Each dataset declares where its targets live so batching and collation logic knows what to expect:

| Target level | Location | Example |
|---|---|---|
| `graph_level` | `frame.metadata` | `energy`, `homo`, `lumo` |
| `atom_level` | `atoms` block columns | `fx`, `fy`, `fz` |

### `InMemoryDataset` / `SubsetDataset`

Convenience helpers for wrapping and slicing:

```python
from molhub.dataset import InMemoryDataset, SubsetDataset

inmem = InMemoryDataset(frames, name="my-frames")         # wrap a list
subset = SubsetDataset(qm9, indices=[0, 10, 100, 1000])  # slice by index
```

## Built-in Datasets

### QM9 (`QM9Source`)

130,831 small organic molecules with quantum-chemical properties.  
Reference: Ramakrishnan et al., *Scientific Data* 1, 140022 (2014).

```python
from molhub.dataset import QM9Source

source = QM9Source("./data/qm9", targets=["U0", "H", "gap"])
# Auto-downloads from Figshare, caches locally, lazy-loads on first access
```

Graph-level targets: `A`, `B`, `C`, `mu`, `alpha`, `homo`, `lumo`, `gap`, `r2`, `zpve`, `U0`, `U`, `H`, `G`, `Cv`.

### revMD17 (`RevMD17Source`)

Revised MD17 molecular dynamics trajectories (10 molecules).  
Reference: Christensen & von Lilienfeld, *MLST* (2020).

```python
from molhub.dataset import RevMD17Source

source = RevMD17Source("./data/revmd17", molecule="aspirin")
frame = source[100]
# atoms block: element, x, y, z, number, fx, fy, fz
# metadata: {'energy': ...}
```

Available molecules: `aspirin`, `azobenzene`, `benzene`, `ethanol`, `malonaldehyde`, `naphthalene`, `paracetamol`, `salicylic`, `toluene`, `uracil`.

### 3BPA (`ThreeBPASource`)

Temperature-transferability benchmark at 300 K, 600 K, and 1200 K.  
Reference: Kovacs et al., *J. Chem. Theory Comput.* (2021).

```python
from molhub.dataset import ThreeBPASource

train = ThreeBPASource("./data/3bpa/train_300K.xyz", tag="train_300K")
test_600 = ThreeBPASource("./data/3bpa/test_600K.xyz", tag="test_600K")
```

### CSVDataset

Generic CSV loader — works on local files and remote URLs. No extra dependencies.

```python
from molhub.dataset import CSVDataset

ds = CSVDataset("/path/to/data.csv")
ds = CSVDataset("https://example.com/data.csv")
# cached to $MOLHUB_CACHE_DIR, falling back to ~/.cache/molhub
```

## Uploaders

### HuggingFace Hub

```python
from molhub.uploader import HuggingFaceUploader

uploader = HuggingFaceUploader(token="hf_...")  # or set HF_TOKEN

uploader.upload_file("data/qm9.tar.bz2", repo_id="my-org/qm9", path_in_repo="raw/qm9.tar.bz2")
uploader.upload_folder("data/processed/", repo_id="my-org/dataset", path_in_repo="processed/")
uploader.upload_dataset("data/dataset.h5", repo_id="my-org/new-dataset")  # create + upload
```

### Figshare

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

## Development

```bash
git clone https://github.com/molcrafts/molhub.git
cd molhub
pip install -e ".[dev]"
pytest --cov=src/molhub --cov-report=term-missing
ruff check src/ tests/
```

| Test file | Covers |
|---|---|
| `test_protocol.py` | `MapDataset`, `IterableDataset`, `TargetSchema`, `InMemoryDataset`, `SubsetDataset` |
| `test_csv_dataset.py` | `CSVDataset` download, parsing, and map-style interface |
| `test_threebpa.py` | `ThreeBPASource` extXYZ parsing |
| `test_uploader.py` | `HuggingFaceUploader`, `FigshareUploader` (mocked HTTP) |

## License

BSD-3-Clause.
