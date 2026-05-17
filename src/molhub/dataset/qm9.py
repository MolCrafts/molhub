"""QM9 data source: 130k small organic molecules with quantum chemical properties.

Reference:
    Ramakrishnan et al. "Quantum chemistry structures and properties of 134 kilo molecules"
    Scientific Data 1, 140022 (2014). https://doi.org/10.1038/sdata.2014.22

Usage::

    from molhub.dataset import QM9Source

    source = QM9Source(data_dir)
    print(len(source))        # 130831
    frame = source[0]         # molpy Frame with atoms block + metadata targets
"""

from __future__ import annotations

import random
import sys
import tarfile
import urllib.request
from pathlib import Path

import numpy as np
from molpy.core.element import Element
from molpy.core.frame import Block, Frame
from tqdm import tqdm

from molhub.dataset.protocol import TargetSchema

# All scalar properties exposed by raw QM9 records (excluding "tag" and "index").
_QM9_GRAPH_TARGETS: frozenset[str] = frozenset(
    {"A", "B", "C", "mu", "alpha", "homo", "lumo", "gap", "r2", "zpve", "U0", "U", "H", "G", "Cv"}
)

# ---------------------------------------------------------------------------
# Raw loader helpers
# ---------------------------------------------------------------------------

_PROPERTY_NAMES = [
    "tag",
    "index",
    "A",
    "B",
    "C",
    "mu",
    "alpha",
    "homo",
    "lumo",
    "gap",
    "r2",
    "zpve",
    "U0",
    "U",
    "H",
    "G",
    "Cv",
]

_DEFAULT_URL = "https://ndownloader.figshare.com/files/3195389"
_EXCLUDE_URL = "https://figshare.com/ndownloader/files/3195404"


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        dest.write_bytes(r.read())


def _load_exclusion_list(path: Path) -> set[int]:
    excluded: set[int] = set()
    for line in path.read_text().splitlines()[9:-1]:
        parts = line.split()
        if parts:
            excluded.add(int(parts[0]))
    return excluded


def _parse_xyz(content: str) -> Frame:
    content = content.replace("*^", "E")
    lines = content.splitlines()
    natoms = int(lines[0].strip())
    prop_values = lines[1].split()
    metadata = dict(zip(_PROPERTY_NAMES, prop_values))

    symbols: list[str] = []
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for line in lines[2 : 2 + natoms]:
        parts = line.split()
        symbols.append(parts[0])
        xs.append(float(parts[1]))
        ys.append(float(parts[2]))
        zs.append(float(parts[3]))

    numbers = [Element.get_atomic_number(s) for s in symbols]

    atoms_blk = Block()
    atoms_blk["element"] = np.array(symbols, dtype="U3")
    atoms_blk["x"] = np.array(xs, dtype=np.float64)
    atoms_blk["y"] = np.array(ys, dtype=np.float64)
    atoms_blk["z"] = np.array(zs, dtype=np.float64)
    atoms_blk["number"] = np.array(numbers, dtype=np.int64)

    targets: dict[str, float] = {}
    for key in _PROPERTY_NAMES:
        if key in ("tag", "index"):
            continue
        targets[key] = float(metadata[key])

    frame = Frame()
    frame["atoms"] = atoms_blk
    frame.metadata.update(targets)
    return frame


def _filter_targets(frame: Frame, kept: frozenset[str]) -> Frame:
    """Drop targets not in *kept* to shrink metadata when user wants a subset."""
    filtered = {k: v for k, v in frame.metadata.items() if k in kept}
    frame.metadata.clear()
    frame.metadata.update(filtered)
    return frame


def _ensure_downloaded(root: Path) -> None:
    """Download the QM9 tarball and exclusion list if not already present.

    Idempotent — safe to call unconditionally.
    """
    root.mkdir(parents=True, exist_ok=True)
    tarball = root / "qm9.tar.bz2"
    exclude_file = root / "qm9_exclude.txt"
    if not tarball.exists():
        print("Downloading QM9 tarball...", flush=True)
        _download(_DEFAULT_URL, tarball)
    if not exclude_file.exists():
        _download(_EXCLUDE_URL, exclude_file)


def _load_raw(root: Path, total: int | None) -> list[Frame]:
    """Return all raw QM9 samples as ``list[Frame]`` (auto-downloads if needed)."""
    _ensure_downloaded(root)
    tarball = root / "qm9.tar.bz2"
    exclude_file = root / "qm9_exclude.txt"

    excluded = _load_exclusion_list(exclude_file)

    members: list[str] = []
    tar_info_cache: dict[str, tarfile.TarInfo] = {}
    with tarfile.open(tarball, "r:bz2") as tar:
        for member in tqdm(tar, desc="Indexing QM9", file=sys.stdout):
            if not member.name.endswith(".xyz"):
                continue
            try:
                mol_idx = int(member.name[-10:-4])
            except ValueError:
                continue
            if mol_idx in excluded:
                continue
            members.append(member.name)
            tar_info_cache[member.name] = member
    members.sort()

    if total is not None and total < len(members):
        random.seed(42)
        members = sorted(random.sample(members, total))

    frames: list[Frame] = []
    with tarfile.open(tarball, "r:bz2") as tar:
        for name in tqdm(members, desc="Loading QM9", file=sys.stdout):
            f = tar.extractfile(tar_info_cache[name])
            assert f is not None
            frames.append(_parse_xyz(f.read().decode("utf-8")))

    return frames


# ---------------------------------------------------------------------------
# QM9Source
# ---------------------------------------------------------------------------


class QM9Source:
    """Map-style dataset for QM9.

    Each sample is a :class:`molpy.core.frame.Frame` with an ``atoms`` block
    (``element``, ``x``, ``y``, ``z``, ``number``) and scalar quantum
    properties stored in ``frame.metadata``.

    Args:
        root: Directory for the raw QM9 tarball (downloaded on first use).
        total: Subsample to at most this many molecules (reproducible seed).
        targets: If given, keep only these scalar properties in each sample.
            ``None`` keeps all of :attr:`QM9Source.ALL_TARGETS`.
        download: Download raw files if missing. Set to ``False`` in
            offline / test environments.

    Class attributes:
        TARGET_SCHEMA: :class:`TargetSchema` covering every scalar target
            that appears in the raw QM9 records (graph-level only).
        ALL_TARGETS: Frozen set of scalar property names.
    """

    SOURCE_VERSION: str = "v2"

    ALL_TARGETS: frozenset[str] = _QM9_GRAPH_TARGETS
    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=_QM9_GRAPH_TARGETS,
        atom_level=frozenset(),
    )

    def __init__(
        self,
        root: str | Path,
        *,
        total: int | None = None,
        targets: list[str] | tuple[str, ...] | None = None,
        download: bool = True,
    ) -> None:
        self.root = Path(root).expanduser().resolve()

        if targets is not None:
            kept = frozenset(targets)
            unknown = kept - _QM9_GRAPH_TARGETS
            if unknown:
                raise ValueError(
                    f"Unknown QM9 targets {sorted(unknown)}. "
                    f"Available: {sorted(_QM9_GRAPH_TARGETS)}"
                )
            self._targets: tuple[str, ...] | None = tuple(sorted(kept))
        else:
            self._targets = None
        self._frames: list[Frame] | None = None
        self._total = total

        if download:
            _ensure_downloaded(self.root)
        else:
            tarball = self.root / "qm9.tar.bz2"
            exclude_file = self.root / "qm9_exclude.txt"
            if not tarball.exists():
                raise FileNotFoundError(
                    f"QM9 tarball not found at {tarball}. "
                    "Set download=True or call QM9Source.download() first."
                )
            if not exclude_file.exists():
                raise FileNotFoundError(
                    f"QM9 exclusion list not found at {exclude_file}. "
                    "Set download=True or call QM9Source.download() first."
                )

    def _ensure_frames_loaded(self) -> None:
        if self._frames is not None:
            return
        frames = _load_raw(self.root, self._total)
        if self._targets is not None:
            kept = frozenset(self._targets)
            frames = [_filter_targets(f.copy(), kept) for f in frames]
        self._frames = frames

    @classmethod
    def download(cls, root: str | Path) -> Path:
        """Ensure raw QM9 files are present in *root*."""
        root = Path(root)
        _ensure_downloaded(root)
        return root

    @property
    def source_id(self) -> str:
        parts = [f"qm9:{self.SOURCE_VERSION}"]
        if self._total is not None:
            parts.append(f"total={self._total}")
        if self._targets is not None:
            parts.append(f"targets={'+'.join(self._targets)}")
        return ":".join(parts)

    def __len__(self) -> int:
        self._ensure_frames_loaded()
        assert self._frames is not None
        return len(self._frames)

    def __getitem__(self, idx: int) -> Frame:
        self._ensure_frames_loaded()
        assert self._frames is not None
        return self._frames[idx]
