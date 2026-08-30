"""QM9 dataset: 130k small organic molecules with quantum chemical properties.

Labels keep the published native units — rotational constants in GHz, dipole
moment in Debye, energies in Hartree, heat capacity in cal/(mol·K) — exactly
as recorded upstream. molhub never converts units; consumers convert (e.g.
:class:`~molhub.dataset.transforms.UnitConvert`). Subsetting is likewise the
consumer's job (:class:`~molhub.dataset.protocol.SubsetDataset`).

Reference:
    Ramakrishnan et al. "Quantum chemistry structures and properties of 134 kilo molecules"
    Scientific Data 1, 140022 (2014). https://doi.org/10.1038/sdata.2014.22

Usage::

    from molhub.dataset import QM9

    ds = QM9().load()
    print(len(ds))            # 130831
    frame = ds[0]             # molpy Frame with atoms block + targets in frame.meta
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import numpy as np
from molpy import Block, Element, Frame
from tqdm import tqdm

from molhub.coordinate import Coordinate
from molhub.dataset.definition import dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import FrameCollection, TargetSchema
from molhub.manifest import Artifact, Manifest, TargetDeclaration
from molhub.molhub import Molhub
from molhub.sources import Digest, Locator

COORDINATE = "dataset:molcrafts/qm9@v2"
"""Where QM9 lives in the catalog. Locators live on :data:`MANIFEST`."""

MANIFEST = Manifest(
    coordinate=Coordinate.parse(COORDINATE),
    title="QM9 — 133,885 small organic molecules with quantum-chemical properties",
    description=(
        "DFT-computed geometries and 15 scalar properties for the GDB-9 subset of "
        "small organic molecules with up to nine heavy atoms (C, N, O, F). The "
        "uncharacterized list names the 3,054 molecules that failed the geometry "
        "consistency check, leaving 130,831 usable entries."
    ),
    license="CC0-1.0",
    doi="10.1038/sdata.2014.22",
    artifacts={
        "main": Artifact(
            role="main",
            filename="dsgdb9nsd.xyz.tar.bz2",
            locators=(Locator.parse("figshare://1057646/v2/dsgdb9nsd.xyz.tar.bz2"),),
            digest=Digest.parse("md5:ad1ebd51ee7f5b3a6e32e974e5d54012"),
            size=86_144_227,
        ),
        "exclude": Artifact(
            role="exclude",
            filename="uncharacterized.txt",
            locators=(Locator.parse("figshare://1057644/v1/uncharacterized.txt"),),
            digest=Digest.parse("md5:a361887bacb427b8a0ce7903d92a53b4"),
            size=486_752,
        ),
    },
    targets=TargetDeclaration(
        graph_level=(
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
        ),
        atom_level=(),
    ),
)

# Names the source has always used on disk in offline mode.
_TARBALL_NAME = "qm9.tar.bz2"
_EXCLUDE_NAME = "qm9_exclude.txt"

# Native units of the 15 scalar properties, per Table 3 of Ramakrishnan 2014.
# Strings parse through the molpy unit registry (UnitConvert reads them back).
_QM9_UNITS: dict[str, str] = {
    "A": "GHz",
    "B": "GHz",
    "C": "GHz",
    "mu": "debye",
    "alpha": "bohr**3",
    "homo": "hartree",
    "lumo": "hartree",
    "gap": "hartree",
    "r2": "bohr**2",
    "zpve": "hartree",
    "U0": "hartree",
    "U": "hartree",
    "H": "hartree",
    "G": "hartree",
    "Cv": "cal/(mol*K)",
}

# All scalar properties exposed by raw QM9 records (excluding "tag" and "index").
_QM9_GRAPH_TARGETS: frozenset[str] = frozenset(_QM9_UNITS)

# uncharacterized.txt wraps its index column in a 9-line preamble and a
# 1-line footer; only the lines between them carry molecule indices.
_EXCLUDE_HEADER_LINES = 9
_EXCLUDE_FOOTER_LINES = 1

# Upstream names each member dsgdb9nsd_NNNNNN.xyz — the molecule index is the
# six digits immediately before the ".xyz" extension.
_XYZ_INDEX = slice(-10, -4)

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


def _is_cached(path: Path) -> bool:
    """True when *path* holds a non-empty file.

    A zero-byte file counts as absent. Treating it as present is what let an
    empty exclusion list silently pass through and inflate the dataset.
    """
    return path.exists() and path.stat().st_size > 0


def _load_exclusion_list(path: Path) -> set[int]:
    excluded: set[int] = set()
    lines = path.read_text().splitlines()
    for line in lines[_EXCLUDE_HEADER_LINES : len(lines) - _EXCLUDE_FOOTER_LINES]:
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

    values: dict[str, float] = {}
    for key in _PROPERTY_NAMES:
        if key in ("tag", "index"):
            continue
        values[key] = float(metadata[key])

    frame = Frame()
    frame["atoms"] = atoms_blk
    frame.meta.update(values)
    return frame


def _locate_files(
    root: Path | None, download: bool, hub: ArtifactHub | None = None
) -> tuple[Path, Path]:
    """Return paths to the QM9 tarball and exclusion list.

    With *download*, the files come from the registry: resolved by coordinate,
    transferred under the source's transport contract, and checked against
    the md5 Figshare publishes for the pinned article version. Without it, they
    must already sit in *root* under the names this dataset has always used.

    Args:
        root: Directory holding pre-downloaded files in offline mode.
        download: Whether to fetch through the hub.
        hub: Any :class:`~molhub.dataset.hub.ArtifactHub`; defaults to a
            freshly constructed :class:`Molhub`.

    Returns:
        ``(tarball, exclusion_list)``.

    Raises:
        FileNotFoundError: In offline mode, if either file is missing or empty.
    """
    if download:
        paths = (hub or Molhub()).fetch(COORDINATE)
        return paths["main"], paths["exclude"]

    base = root if root is not None else Path()
    tarball = base / _TARBALL_NAME
    exclude_file = base / _EXCLUDE_NAME
    if not _is_cached(tarball):
        raise FileNotFoundError(
            f"QM9 tarball not found at {tarball}. Set download=True or place the file there first."
        )
    if not _is_cached(exclude_file):
        raise FileNotFoundError(
            f"QM9 exclusion list not found at {exclude_file}. "
            "Set download=True or place the file there first."
        )
    return tarball, exclude_file


def _load_raw(
    root: Path | None, *, download: bool = False, hub: ArtifactHub | None = None
) -> list[Frame]:
    """Return all characterized QM9 samples as ``list[Frame]``, in index order.

    One pass over the bz2 tarball: each member is parsed as it streams by,
    so the archive is decompressed exactly once.
    """
    tarball, exclude_file = _locate_files(root, download, hub)

    excluded = _load_exclusion_list(exclude_file)

    frames_by_name: dict[str, Frame] = {}
    with tarfile.open(tarball, "r:bz2") as tar:
        for member in tqdm(tar, desc="Loading QM9"):
            if not member.name.endswith(".xyz"):
                continue
            try:
                mol_idx = int(member.name[_XYZ_INDEX])
            except ValueError:
                continue
            if mol_idx in excluded:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            frames_by_name[member.name] = _parse_xyz(handle.read().decode("utf-8"))

    return [frames_by_name[name] for name in sorted(frames_by_name)]


# ---------------------------------------------------------------------------
# QM9
# ---------------------------------------------------------------------------


@dataset(
    name="qm9",
    namespace="molcrafts",
    version="v2",
    description="130k small organic molecules with quantum-chemical properties.",
    license="CC0-1.0",
    citation="10.1038/sdata.2014.22",
    tags=("qm", "energy"),
    units=_QM9_UNITS,
)
class QM9:
    """Map-style dataset for QM9.

    Construction does no IO. :meth:`load` is the fetch-and-parse boundary;
    after it, each sample is a :class:`molpy.Frame` with an ``atoms`` block
    (``element``, ``x``, ``y``, ``z``, ``number``) and all 15 scalar quantum
    properties in ``frame.meta``, in their published native units.

    Subsetting and target pruning are the consumer's job — wrap with
    :class:`~molhub.dataset.protocol.SubsetDataset` or drop meta keys in a
    transform; this class carries no view knobs of its own.

    Args:
        root: Directory holding pre-downloaded files in offline mode. Ignored
            when *download* is true (fetched files land in the shared cache).
        download: Download raw files if missing. Set to ``False`` in
            offline / test environments.
        hub: Anything satisfying :class:`~molhub.dataset.hub.ArtifactHub`.
            Defaults to a freshly constructed :class:`~molhub.molhub.Molhub`.

    Class attributes:
        COORDINATE: The pinned registry coordinate.
        TARGET_SCHEMA: :class:`TargetSchema` covering every scalar target
            that appears in the raw QM9 records (graph-level only).
        ALL_TARGETS: Frozen set of scalar property names.
    """

    COORDINATE = COORDINATE
    ALL_TARGETS: frozenset[str] = _QM9_GRAPH_TARGETS
    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=_QM9_GRAPH_TARGETS,
        atom_level=frozenset(),
    )

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        download: bool = True,
        hub: ArtifactHub | None = None,
    ) -> None:
        self.root = Path(root).expanduser() if root is not None else None
        self._download = download
        self._hub = hub
        self._frames: list[Frame] | None = None

    def load(self) -> QM9:
        """Locate or fetch the raw files and parse every characterized frame.

        Idempotent: a second call returns immediately.

        Returns:
            This dataset, now indexable.

        Raises:
            FileNotFoundError: Offline mode and a raw file is missing or empty.
        """
        if self._frames is None:
            self._frames = _load_raw(self.root, download=self._download, hub=self._hub)
        return self

    def _require_loaded(self) -> list[Frame]:
        if self._frames is None:
            raise RuntimeError("QM9: call load() before indexing; construction does no IO.")
        return self._frames

    @property
    def source_id(self) -> str:
        """A cache key for this dataset: the coordinate, nothing else.

        The whole content is one view, so the id round-trips through
        :meth:`Coordinate.parse`. Subset views get their qualifier from
        :class:`~molhub.dataset.protocol.SubsetDataset`, not from here.
        """
        return COORDINATE

    def __len__(self) -> int:
        return len(self._require_loaded())

    def __getitem__(self, idx: int) -> FrameCollection:
        return (self._require_loaded()[idx],)
