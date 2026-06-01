"""3BPA DataSource: temperature-transferability benchmark for MLPs.

Reference:
    Kovacs et al., "Linear Atomic Cluster Expansion Force Fields for
    Organic Molecules: Beyond RMSE" J. Chem. Theory Comput. 2021.
    https://doi.org/10.1021/acs.jctc.1c00647

3BPA = 3-(benzyloxy)pyridin-2-amine (C13H14N2O). The benchmark ships
four extended-XYZ files:

  * ``train_300K.xyz``   — 500 structures sampled at 300 K (training pool).
  * ``test_300K.xyz``    — held-out 300 K structures (in-distribution).
  * ``test_600K.xyz``    — held-out 600 K  (temperature extrapolation).
  * ``test_1200K.xyz``   — held-out 1200 K (harder extrapolation).

Usage::

    from molhub.dataset import ThreeBPASource

    src_train = ThreeBPASource(data_dir / "train_300K.xyz", tag="train_300K")
    src_600   = ThreeBPASource(data_dir / "test_600K.xyz",  tag="test_600K")
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from molpy.core.element import Element
from molpy.core.frame import Block, Frame

from molhub.dataset.protocol import TargetSchema


def _parse_extxyz(path: Path) -> list[Frame]:
    """Parse an extended-XYZ file shipped with the 3BPA benchmark."""
    frames: list[Frame] = []
    lines = path.read_text().splitlines()
    i = 0
    while i < len(lines):
        natoms = int(lines[i].strip())
        comment = lines[i + 1]
        energy: float | None = None
        for tok in comment.split():
            if tok.startswith("energy="):
                energy = float(tok.split("=", 1)[1])
                break
        if energy is None:
            raise ValueError(f"Missing 'energy=...' tag in {path} at structure {len(frames)}")

        symbols: list[str] = []
        xs: list[float] = []
        ys: list[float] = []
        zs: list[float] = []
        fxs: list[float] = []
        fys: list[float] = []
        fzs: list[float] = []

        for row in lines[i + 2 : i + 2 + natoms]:
            parts = row.split()
            symbols.append(parts[0])
            xs.append(float(parts[1]))
            ys.append(float(parts[2]))
            zs.append(float(parts[3]))
            fxs.append(float(parts[4]))
            fys.append(float(parts[5]))
            fzs.append(float(parts[6]))

        numbers = [Element.get_atomic_number(s) for s in symbols]

        atoms_blk = Block()
        atoms_blk["element"] = np.array(symbols, dtype="U3")
        atoms_blk["x"] = np.array(xs, dtype=np.float64)
        atoms_blk["y"] = np.array(ys, dtype=np.float64)
        atoms_blk["z"] = np.array(zs, dtype=np.float64)
        atoms_blk["number"] = np.array(numbers, dtype=np.int64)
        atoms_blk["fx"] = np.array(fxs, dtype=np.float64)
        atoms_blk["fy"] = np.array(fys, dtype=np.float64)
        atoms_blk["fz"] = np.array(fzs, dtype=np.float64)

        frame = Frame()
        frame["atoms"] = atoms_blk
        frame.metadata["energy"] = energy
        frames.append(frame)

        i += 2 + natoms
    return frames


class ThreeBPASource:
    """Map-style dataset for one 3BPA extended-XYZ split.

    Each sample is a :class:`molpy.core.frame.Frame` with an ``atoms`` block
    (``element``, ``x``, ``y``, ``z``, ``number``, ``fx``, ``fy``, ``fz``)
    and ``energy`` in ``frame.metadata``.

    Args:
        path: Path to the ``.xyz`` file.
        tag: Short identifier of the split (e.g. ``"train_300K"``).
    """

    TARGET_SCHEMA: TargetSchema = TargetSchema(
        graph_level=frozenset({"energy"}),
        atom_level=frozenset({"forces"}),
    )

    def __init__(self, path: str | Path, *, tag: str) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"3BPA file not found: {self.path}. Download the benchmark "
                "from the Kovacs et al. (2021) supplementary material."
            )
        self.tag = tag
        self._frames = _parse_extxyz(self.path)
        self._size = self.path.stat().st_size

    @property
    def source_id(self) -> str:
        return f"3bpa:{self.tag}:size={self._size}:n={len(self._frames)}"

    def __len__(self) -> int:
        return len(self._frames)

    def __getitem__(self, idx: int) -> Frame:
        return self._frames[idx]
