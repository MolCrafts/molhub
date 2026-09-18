"""WaterLES: bulk liquid water (RPBE-D3) from the latent-Ewald benchmark suite.

Reference:
    Cheng B., "Latent Ewald summation for machine-learning potentials"
    npj Comput. Mater. **11**:80 (2025). https://doi.org/10.1038/s41524-025-01577-7

The upstream ``les_fit`` benchmark ships two extended-XYZ files, which this
module calls *roles* on the artifact at :data:`COORDINATE`:

* ``train-H2O_RPBE-D3.xyz`` — the pooled train + validation snapshots, split
  0.95 / 0.05 by a deterministic **tail slice** (the last
  ``n - ceil(0.95 n)`` frames are validation; no shuffle), which is the split
  the upstream ``lr_r45_nlayer3_lmax2.yaml`` recipe uses.
* ``test-H2O_RPBE-D3.xyz`` — the independent held-out test split.

Each frame is a periodic cubic box of H₂O. **Units pass through unscaled**:
energies in eV, forces in eV·Å⁻¹, positions and cell in Å, exactly as written
upstream. A silent Hartree→eV or Å→nm rescale here would be invisible in
training and catastrophic in the reported error, so this module applies no
factor at all — rescaling is
:class:`~molhub.dataset.transforms.UnitConvert`'s job, opted into by name.

Usage::

    from molhub.dataset.water_les import WaterLESDataset

    train = WaterLESDataset("~/data/water_les", split="train").load()
    val = WaterLESDataset("~/data/water_les", split="val").load()
    test = WaterLESDataset(split="test").load()  # retrieved by coordinate

Why this module parses extended-XYZ itself rather than reusing
:func:`molhub.dataset.threebpa._parse_extxyz`: 3BPA's molecules are aperiodic
and its parser reads fixed columns, so it neither carries ``Lattice`` onto
``Frame.box`` nor can tell a caller that a file declares no ``forces`` column.
Both are load-bearing here — the cell *is* the physics of bulk water, and a
forceless file cannot satisfy :attr:`WaterLESDataset.TARGET_SCHEMA`. Folding
those into 3BPA's parser belongs to whoever unifies the two, not to this spec.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from molpy import Block, Box, Element, Frame

from molhub.dataset.definition import dataset
from molhub.dataset.hub import ArtifactHub
from molhub.dataset.protocol import Dataset, TargetSchema
from molhub.dataset.statistic import StatisticMixin
from molhub.molhub import Molhub

__all__ = ["COORDINATE", "WaterLESDataset"]

COORDINATE = "dataset:molcrafts/water-les@1"
"""Where WaterLES lives in the registry.

Its manifest carries the locators and the digests; this module holds no
upstream URL and checks no hash of its own — integrity is the registry's
concern, and duplicating it here is how two sources of truth start.
"""

#: ``key=value`` fields of an extended-XYZ comment line. A quoted value may
#: hold spaces (``Lattice="12.0 0.0 …"``), which is why this is a regex and
#: not a ``str.split``.
_COMMENT_FIELD = re.compile(r'([A-Za-z_][\w-]*)=("[^"]*"|\S+)')


def _comment_fields(comment: str) -> dict[str, str]:
    """Parse the ``key=value`` fields of one extended-XYZ comment line."""
    return {match[1]: match[2].strip('"') for match in _COMMENT_FIELD.finditer(comment)}


def _column_spans(properties: str) -> dict[str, tuple[int, int]]:
    """Map each ``Properties`` field to its ``(first column, width)`` span.

    ``Properties=species:S:1:pos:R:3:forces:R:3`` is a flat list of
    ``name:type:count`` triples describing the atom rows left to right.

    Raises:
        ValueError: The declaration is not a whole number of triples.
    """
    tokens = properties.split(":")
    if not tokens or len(tokens) % 3 != 0:
        raise ValueError(f"Malformed extended-XYZ Properties declaration: {properties!r}.")
    spans: dict[str, tuple[int, int]] = {}
    first = 0
    for name, width in zip(tokens[0::3], tokens[2::3]):
        count = int(width)
        spans[name] = (first, count)
        first += count
    return spans


def _lattice(fields: dict[str, str]) -> Box | None:
    """The frame's cell as a :class:`molpy.Box`, or ``None`` when aperiodic."""
    lattice = fields.get("Lattice")
    if lattice is None:
        return None
    values = np.asarray([float(token) for token in lattice.split()], dtype=np.float64)
    if values.size != 9:
        raise ValueError(f"Extended-XYZ Lattice needs 9 numbers, got {values.size}.")
    return Box(values.reshape(3, 3))


def _parse_water_extxyz(path: Path) -> list[Frame]:
    """Parse every frame of a WaterLES extended-XYZ file.

    Args:
        path: The ``.xyz`` file to read.

    Returns:
        One :class:`molpy.Frame` per structure, with an ``atoms`` block
        (``element``, ``x``, ``y``, ``z``, ``number``, ``fx``, ``fy``, ``fz``),
        the cell on :attr:`Frame.box`, and ``energy`` in ``frame.meta``.

    Raises:
        ValueError: A frame declares no ``energy``, no ``pos`` or ``species``
            column, or no ``forces`` column.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    frames: list[Frame] = []
    cursor = 0
    while cursor < len(lines):
        n_atoms = int(lines[cursor].strip())
        fields = _comment_fields(lines[cursor + 1])

        if "energy" not in fields:
            raise ValueError(f"{path}: structure {len(frames)} declares no 'energy='.")
        spans = _column_spans(fields.get("Properties", "species:S:1:pos:R:3"))
        for required in ("species", "pos"):
            if required not in spans:
                raise ValueError(
                    f"{path}: structure {len(frames)} declares no {required!r} column."
                )
        if "forces" not in spans:
            raise ValueError(
                f"{path}: structure {len(frames)} declares no 'forces' column in "
                f"Properties, so it cannot satisfy the WaterLES target schema."
            )

        species_at, _ = spans["species"]
        pos_at, _ = spans["pos"]
        force_at, _ = spans["forces"]
        symbols: list[str] = []
        positions = np.empty((n_atoms, 3), dtype=np.float64)
        forces = np.empty((n_atoms, 3), dtype=np.float64)
        for row, line in enumerate(lines[cursor + 2 : cursor + 2 + n_atoms]):
            columns = line.split()
            symbols.append(columns[species_at])
            positions[row] = [float(value) for value in columns[pos_at : pos_at + 3]]
            forces[row] = [float(value) for value in columns[force_at : force_at + 3]]

        atoms = Block()
        atoms["element"] = np.asarray(symbols, dtype="U3")
        atoms["x"] = positions[:, 0]
        atoms["y"] = positions[:, 1]
        atoms["z"] = positions[:, 2]
        atoms["number"] = np.asarray(
            [Element.get_atomic_number(symbol) for symbol in symbols], dtype=np.int64
        )
        atoms["fx"] = forces[:, 0]
        atoms["fy"] = forces[:, 1]
        atoms["fz"] = forces[:, 2]

        frame = Frame()
        frame["atoms"] = atoms
        box = _lattice(fields)
        if box is not None:
            frame.box = box
        frame.meta = {"energy": float(fields["energy"])}
        frames.append(frame)

        cursor += 2 + n_atoms
    return frames


@dataset(
    name="water-les",
    namespace="molcrafts",
    version="1",
    description="Bulk liquid water (RPBE-D3) snapshots from the latent-Ewald benchmark.",
    license="MIT",
    homepage="https://github.com/ChengUCB/les_fit",
    citation="10.1038/s41524-025-01577-7",
    tags=("water", "periodic", "energy", "forces", "dft"),
    # Unscaled pass-through, as this module's docstring states: energies in eV,
    # forces in eV per angstrom. ASCII and solidus-composed, not the prose
    # `eV·Å⁻¹`, because `molhub.dataset.transforms.UnitConvert` parses these
    # strings back through the molpy unit registry.
    units={"energy": "eV", "forces": "eV/angstrom"},
)
class WaterLESDataset(Dataset, StatisticMixin):
    """One split of the WaterLES benchmark, declared on the ``@dataset`` protocol.

    Construction does no IO. :meth:`load` is the fetch-and-parse boundary, so
    naming a split costs nothing until the frames are actually wanted.

    Args:
        root: Directory holding :attr:`TRAIN_FILE` and/or :attr:`TEST_FILE`.
            When the needed file is missing or empty there, the split's role
            is retrieved through *hub* instead and the bytes land in the
            shared cache. ``None`` always retrieves.
        split: ``"train"``, ``"val"`` or ``"test"``. ``train`` and ``val``
            are two views of one upstream file and fetch the same role once.
        hub: Anything satisfying :class:`~molhub.dataset.hub.ArtifactHub`;
            defaults to a :class:`~molhub.molhub.Molhub`.

    Raises:
        ValueError: *split* is not one of :attr:`SPLITS`.

    Class attributes:
        TRAIN_FILE / TEST_FILE: Upstream basenames, also the manifest roles.
        TRAIN_VAL_RATIO: The upstream recipe's deterministic tail split.
        SPLITS: The three named views.
        TARGET_SCHEMA: Energy is graph-level, forces are atom-level.
    """

    COORDINATE = COORDINATE
    TRAIN_FILE: str = "train-H2O_RPBE-D3.xyz"
    TEST_FILE: str = "test-H2O_RPBE-D3.xyz"
    TRAIN_VAL_RATIO: tuple[float, float] = (0.95, 0.05)
    SPLITS: frozenset[str] = frozenset({"train", "val", "test"})
    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
    )

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        split: str,
        hub: ArtifactHub | None = None,
    ) -> None:
        if split not in self.SPLITS:
            raise ValueError(
                f"WaterLESDataset: unknown split {split!r}; expected one of {sorted(self.SPLITS)}."
            )
        self.root = Path(root).expanduser() if root is not None else None
        self.split = split
        self._hub = hub
        self._frames: list[Frame] | None = None

    @property
    def source_id(self) -> str:
        """Cache identity of this view: the coordinate plus the split.

        Everything before the ``#`` round-trips through
        :meth:`~molhub.coordinate.Coordinate.parse`; what follows names a
        view of that artifact, not an artifact. Nothing local goes in — molnex
        folded the file's byte size and frame count into its key, which made
        the identity unaddressable from anywhere but the machine that built it.
        """
        return f"{COORDINATE}#split={self.split}"

    def load(self) -> WaterLESDataset:
        """Retrieve or locate this split's file and parse its frames.

        Idempotent: a second call returns immediately. The returned dataset
        keeps this view's :attr:`source_id` — the coordinate plus the split,
        never a local frame count.

        Returns:
            This dataset, now indexable in file order.

        Raises:
            ValueError: A structure declares no forces column.
        """
        if self._frames is None:
            self._frames = self._select(_parse_water_extxyz(self._locate()))
        return self

    def __len__(self) -> int:
        return len(self._require_loaded())

    def __getitem__(self, idx: int) -> Sequence[Frame]:
        return (self._require_loaded()[idx],)

    def _require_loaded(self) -> list[Frame]:
        if self._frames is None:
            raise RuntimeError(
                "WaterLESDataset: call load() before indexing; construction does no IO."
            )
        return self._frames

    def _select(self, frames: list[Frame]) -> list[Frame]:
        """Apply the deterministic tail split to a parsed train pool."""
        if self.split == "test":
            return frames
        n_train = math.ceil(len(frames) * self.TRAIN_VAL_RATIO[0])
        return frames[:n_train] if self.split == "train" else frames[n_train:]

    def _locate(self) -> Path:
        """Return the file to parse, retrieving it when nothing usable is local.

        A zero-byte file counts as absent: that is what an interrupted
        download leaves behind, and parsing it yields a silently empty split.
        """
        role = "test" if self.split == "test" else "train"
        filename = self.TEST_FILE if self.split == "test" else self.TRAIN_FILE
        if self.root is not None:
            candidate = self.root / filename
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        hub = self._hub if self._hub is not None else Molhub()
        return hub.fetch(COORDINATE, roles=[role])[role]
