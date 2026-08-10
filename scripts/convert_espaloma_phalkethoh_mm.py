#!/usr/bin/env python3
"""Convert Espaloma ``small_phalkethoh_mm.zip`` → MolHub normalized layout.

Espaloma ships DGL heterographs (``u_ref`` in Hartree, 100 conformers/molecule).
This script requires a Python with ``dgl`` installed (often a separate env) and
writes the Frame-friendly layout expected by :class:`molhub.dataset.PhalkethohMMDataset`:

::

    out/
      splits.json          # molecule-level 80/10/10, seed=2666 (Espaloma notebook)
      mols/<id>/
        atoms.npz          # number, atomi, atomj
        confs.npz          # coords (C,N,3) Å, mm_energy (C,) kcal/mol
        legacy_params.json # optional bond/angle ref params from the graph

Usage::

    python scripts/convert_espaloma_phalkethoh_mm.py \\
        --src small_phalkethoh_mm.zip \\
        --out phalkethoh-mm-small-normalized

Reference:
    Espaloma MM-small notebook (shuffle seed 2666, split 8:1:1).
    Energy conversion: 1 Hartree = 627.5094740631 kcal/mol.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import zipfile
from pathlib import Path

import numpy as np

HARTREE_TO_KCAL = 627.5094740631
DEFAULT_SEED = 2666
DEFAULT_RATIOS = (0.8, 0.1, 0.1)


def _require_dgl():
    try:
        import dgl  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "dgl is required for conversion (pip install 'dgl==1.1.3' on a "
            "compatible Python). Unit tests use synthetic normalized fixtures "
            "and do not need this script."
        ) from exc
    return __import__("dgl")


def convert(src: Path, out: Path, *, seed: int = DEFAULT_SEED) -> dict:
    dgl = _require_dgl()
    out.mkdir(parents=True, exist_ok=True)
    mols_dir = out / "mols"
    if mols_dir.exists():
        shutil.rmtree(mols_dir)
    mols_dir.mkdir()
    tmp = out / "_dgl_tmp"
    tmp.mkdir(exist_ok=True)

    z = zipfile.ZipFile(src)
    ids = sorted(
        {
            n.split("/")[1]
            for n in z.namelist()
            if n.startswith("phalkethoh/") and len(n.split("/")) >= 3
        }
    )
    if not ids:
        raise SystemExit(f"no phalkethoh/* entries in {src}")

    def load_mol_json(mid: str) -> dict:
        raw = z.read(f"phalkethoh/{mid}/mol.json")
        return json.loads(json.loads(raw))

    for mid in ids:
        mol = load_mol_json(mid)
        numbers = np.array([a["atomic_number"] for a in mol["atoms"]], dtype=np.int64)
        bi = np.array([b["atom1"] for b in mol["bonds"]], dtype=np.int64)
        bj = np.array([b["atom2"] for b in mol["bonds"]], dtype=np.int64)

        (tmp / "heterograph.bin").write_bytes(z.read(f"phalkethoh/{mid}/heterograph.bin"))
        gs, _ = dgl.load_graphs(str(tmp / "heterograph.bin"))
        g = gs[0]
        xyz = g.nodes["n1"].data["xyz"].detach().cpu().numpy()  # (N, C, 3)
        u = g.nodes["g"].data["u_ref"].detach().cpu().numpy().reshape(-1)
        n_confs = xyz.shape[1]
        if u.shape[0] != n_confs:
            raise RuntimeError(f"{mid}: u_ref length {u.shape[0]} != n_confs {n_confs}")

        legacy: dict = {}
        if g.num_nodes("n2") > 0:
            legacy["bond_k_ref"] = g.nodes["n2"].data["k_ref"].detach().cpu().numpy().reshape(-1).tolist()
            legacy["bond_eq_ref"] = g.nodes["n2"].data["eq_ref"].detach().cpu().numpy().reshape(-1).tolist()
            legacy["bond_idxs"] = g.nodes["n2"].data["idxs"].detach().cpu().numpy().astype(int).tolist()
        if g.num_nodes("n3") > 0 and "k_ref" in g.nodes["n3"].data:
            legacy["angle_k_ref"] = g.nodes["n3"].data["k_ref"].detach().cpu().numpy().reshape(-1).tolist()
            legacy["angle_eq_ref"] = g.nodes["n3"].data["eq_ref"].detach().cpu().numpy().reshape(-1).tolist()
            legacy["angle_idxs"] = g.nodes["n3"].data["idxs"].detach().cpu().numpy().astype(int).tolist()

        md = mols_dir / mid
        md.mkdir()
        coords = np.transpose(xyz, (1, 0, 2)).astype(np.float64)
        mm_energy = u.astype(np.float64) * HARTREE_TO_KCAL
        np.savez_compressed(md / "atoms.npz", number=numbers, atomi=bi, atomj=bj)
        np.savez_compressed(md / "confs.npz", coords=coords, mm_energy=mm_energy)
        if legacy:
            (md / "legacy_params.json").write_text(json.dumps(legacy))

    rng = random.Random(seed)
    shuffled = ids[:]
    rng.shuffle(shuffled)
    n = len(shuffled)
    n_train = int(n * DEFAULT_RATIOS[0])
    n_val = int(n * DEFAULT_RATIOS[1])
    splits = {
        "train": shuffled[:n_train],
        "val": shuffled[n_train : n_train + n_val],
        "test": shuffled[n_train + n_val :],
        "seed": seed,
        "ratios": list(DEFAULT_RATIOS),
        "scheme": "espaloma-original",
    }
    (out / "splits.json").write_text(json.dumps(splits, indent=2) + "\n")
    shutil.rmtree(tmp, ignore_errors=True)
    return {
        "n_molecules": len(ids),
        "n_conformers": n * 100,
        "split": {k: len(v) for k, v in splits.items() if isinstance(v, list)},
        "out": str(out),
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, required=True, help="Espaloma small_phalkethoh_mm.zip")
    p.add_argument("--out", type=Path, required=True, help="Output directory (normalized tree)")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = p.parse_args()
    stats = convert(args.src, args.out, seed=args.seed)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
