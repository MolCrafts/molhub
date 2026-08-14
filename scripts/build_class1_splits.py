#!/usr/bin/env python3
"""Build the Class-I universal identity + split manifests from THEMol indexes.

Implements `.claude/specs/universal-class-i-01-dataset-composition.md` §18/§19
(ac-005): normalize molecular graphs -> global molecular identity ->
molecule-level train/validation/test split -> only then configuration
sampling. All structures belonging to one molecular identity stay in one
split; a torsion scan inherits its molecule's split (scan rows key the same
identity), so grouped targets can never straddle splits.

Global identity
    THEMol's ``mapped_isomeric_smiles`` strings are byte-identical for the
    same molecule across the hessian / torsion-scan / mbis subsets (verified
    2026-08-14: 2,371,035 of the 2,436,985 torsion molecules match hessian
    strings exactly), so identity = blake2b-128 of that string. The
    torsion-scan ``uuid`` column is a *scan* identity, not a molecule
    identity (zero uuid overlap with hessian/mbis) — do not key splits on it.

Outputs (under ``$MOLHUB_HOME/derived/molcrafts/class1-universal-splits/1/``):
    identity_splits.csv.gz        identity,split          one row per molecule
    hessian_uuid_splits.csv.gz    uuid,identity,split     per hessian molecule
    mbis_uuid_splits.csv.gz       uuid,identity,split     per mbis molecule
    torsion_scan_splits.csv.gz    uuid,identity,split     per torsion scan
    metadata.json                 seed, ratios, counts, input sha256s

Deterministic and re-runnable: same inputs + seed -> byte-identical outputs.

Usage:
    MOLHUB_HOME=/path/to/molhub-home \
    python scripts/build_class1_splits.py [--seed 20260814]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

RATIOS = (8, 1, 1)  # train : val : test, molecule level (espaloma precedent)
SOURCES = {
    "hessian": "dataset:themol/hessian@1",
    "torsion-scan": "dataset:themol/torsion-scan@1",
    "mbis": "dataset:themol/mbis@1",
}
SMILES_COL = "mapped_isomeric_smiles"


def identity_of(smiles: str) -> str:
    return hashlib.blake2b(smiles.encode(), digest_size=16).hexdigest()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_index(path: Path) -> list[tuple[str, str]]:
    """Return (uuid, identity) rows in file order."""
    rows: list[tuple[str, str]] = []
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        uuid_col = header.index("uuid")
        smiles_col = header.index(SMILES_COL)
        for row in reader:
            rows.append((row[uuid_col], identity_of(row[smiles_col])))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument(
        "--molhub-home",
        type=Path,
        default=Path(os.environ.get("MOLHUB_HOME", Path.home() / ".cache" / "molhub")),
    )
    args = parser.parse_args()

    home = args.molhub_home
    out_dir = home / "derived" / "molcrafts" / "class1-universal-splits" / "1"
    out_dir.mkdir(parents=True, exist_ok=True)

    index_paths = {name: home / "files" / f"dataset/themol/{name}@1" / "index" for name in SOURCES}
    for name, path in index_paths.items():
        if not path.exists():
            print(f"missing index for {name}: {path}", file=sys.stderr)
            return 1

    print("hashing input indexes ...", flush=True)
    input_digests = {name: sha256_of(path) for name, path in index_paths.items()}

    print("reading indexes ...", flush=True)
    per_source = {name: read_index(path) for name, path in index_paths.items()}

    universe = sorted({identity for rows in per_source.values() for _, identity in rows})
    rng = random.Random(args.seed)
    rng.shuffle(universe)
    n = len(universe)
    total = sum(RATIOS)
    n_train = n * RATIOS[0] // total
    n_val = n * RATIOS[1] // total
    split_of: dict[str, str] = {}
    for i, identity in enumerate(universe):
        split_of[identity] = "train" if i < n_train else "val" if i < n_train + n_val else "test"

    with gzip.open(out_dir / "identity_splits.csv.gz", "wt", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["identity", "split"])
        for identity in sorted(split_of):
            writer.writerow([identity, split_of[identity]])

    counts: dict[str, dict[str, int]] = {}
    for name, rows in per_source.items():
        out_name = f"{name.replace('-', '_')}_{'scan' if name == 'torsion-scan' else 'uuid'}"
        out_name = {
            "hessian": "hessian_uuid_splits.csv.gz",
            "mbis": "mbis_uuid_splits.csv.gz",
            "torsion-scan": "torsion_scan_splits.csv.gz",
        }[name]
        tally = {"train": 0, "val": 0, "test": 0}
        with gzip.open(out_dir / out_name, "wt", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["uuid", "identity", "split"])
            for uuid, identity in rows:
                split = split_of[identity]
                tally[split] += 1
                writer.writerow([uuid, identity, split])
        counts[name] = tally

    metadata = {
        "coordinate": "dataset:molcrafts/class1-universal-splits@1",
        "spec": "molhub:.claude/specs/universal-class-i-01-dataset-composition.md (ac-005)",
        "identity": f"blake2b-128 of {SMILES_COL} (byte-identical across THEMol subsets)",
        "seed": args.seed,
        "ratios": "8:1:1 train:val:test, molecule level",
        "n_identities": n,
        "identity_counts": {
            "train": n_train,
            "val": n_val,
            "test": n - n_train - n_val,
        },
        "per_source_row_counts": counts,
        "source_coordinates": SOURCES,
        "input_index_sha256": input_digests,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generator": "scripts/build_class1_splits.py",
        "output_sha256": {},
    }
    for out_name in (
        "identity_splits.csv.gz",
        "hessian_uuid_splits.csv.gz",
        "mbis_uuid_splits.csv.gz",
        "torsion_scan_splits.csv.gz",
    ):
        metadata["output_sha256"][out_name] = sha256_of(out_dir / out_name)
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    print(json.dumps({k: v for k, v in metadata.items() if k != "output_sha256"}, indent=2))
    print(f"outputs -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
