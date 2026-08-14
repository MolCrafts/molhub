#!/usr/bin/env python3
"""Generate immutable THEMol registry manifests from its official inventory.

The input is ByteDance-Seed/THEMol's ``moleculedataset/tests/sha256_ref.csv``.
Generation is deliberately strict: it accepts only the reviewed five-subset
inventory and writes byte-identical files to MolHub's bundled snapshot and the
external data-only registry.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

HF_COMMIT = "e029fa677b2638b29efa5930a1173d4e41abcab8"
SOURCE_REPOSITORY = "ByteDance-Seed/THEMol"


@dataclass(frozen=True)
class Source:
    directory: str
    name: str
    title: str
    description: str
    graph_targets: tuple[str, ...]
    atom_targets: tuple[str, ...]
    expected_files: int
    expected_bytes: int


SOURCES = (
    Source(
        directory="Hessian",
        name="hessian",
        title="THEMol equilibrium geometries and Hessians",
        description=(
            "THEMol optimized molecular structures and Cartesian Hessians at "
            "B3LYP-D3(BJ)/DZVP. Coordinates are angstrom and Hessians are "
            "kcal mol^-1 angstrom^-2. Each HDF5 UUID is one mapped molecular "
            "identity; topology is reconstructed in atom-map order."
        ),
        graph_targets=("hessian",),
        atom_targets=(),
        expected_files=51,
        expected_bytes=240_902_194_997,
    ),
    Source(
        directory="HessianRelax",
        name="hessian-relax",
        title="THEMol Hessian relaxation trajectories",
        description=(
            "THEMol off-equilibrium geometry-optimization trajectories at "
            "B3LYP-D3(BJ)/DZVP. Energies are kcal mol^-1, coordinates are "
            "angstrom, and forces are kcal mol^-1 angstrom^-1. UUID and ordered "
            "step membership are preserved."
        ),
        graph_targets=("energy",),
        atom_targets=("forces",),
        expected_files=53,
        expected_bytes=1_048_543_472_353,
    ),
    Source(
        directory="TorsionScan",
        name="torsion-scan",
        title="THEMol constrained torsion profiles",
        description=(
            "THEMol constrained torsion profiles at B3LYP-D3(BJ)/DZVP. "
            "Energies are kcal mol^-1, coordinates are angstrom, and forces are "
            "kcal mol^-1 angstrom^-1. Each UUID is a complete ordered scan with "
            "its four mapped torsion atoms and constraint membership intact."
        ),
        graph_targets=("energy", "torsion_angle"),
        atom_targets=("forces",),
        expected_files=51,
        expected_bytes=346_958_500_568,
    ),
    Source(
        directory="TorsionScanRelax",
        name="torsion-relax",
        title="THEMol torsion-constrained relaxation trajectories",
        description=(
            "THEMol off-equilibrium trajectories grouped by constrained torsion "
            "profile at B3LYP-D3(BJ)/DZVP. Energies are kcal mol^-1, coordinates "
            "are angstrom, and forces are kcal mol^-1 angstrom^-1. UUID, "
            "constraint, and ordered optimization-step membership are preserved."
        ),
        graph_targets=("energy", "torsion_angle"),
        atom_targets=("forces",),
        expected_files=469,
        expected_bytes=4_805_506_542_234,
    ),
    Source(
        directory="MBIS",
        name="mbis",
        title="THEMol MBIS atomic electrostatics",
        description=(
            "THEMol MBIS electrostatic targets at PBE0/def2-TZVPD (DZVP for "
            "iodine). Coordinates are angstrom; charges are e, dipoles e "
            "angstrom, quadrupoles e angstrom^2, volumes angstrom^3, and inverse "
            "Slater widths angstrom^-1. This source remains separate from the "
            "B3LYP-D3(BJ)/DZVP energy and force sources."
        ),
        graph_targets=(),
        atom_targets=(
            "atomic_charge",
            "atomic_dipole",
            "atomic_quadrupole",
            "atomic_volume",
            "mbis_parameters",
        ),
        expected_files=9,
        expected_bytes=31_041_658_614,
    ),
)


def _role(path: str) -> str:
    filename = Path(path).name
    if filename.endswith("_dataset.csv"):
        return "index"
    stem = Path(filename).stem
    shard_number = int(stem.rsplit("_", 1)[1])
    return f"shard-{shard_number:03d}"


def _sort_key(row: dict[str, str]) -> tuple[int, int]:
    role = _role(row["relative_path"])
    return (0, -1) if role == "index" else (1, int(role.split("-")[1]))


def _yaml_list(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(values) + "]"


def _render(source: Source, rows: list[dict[str, str]]) -> str:
    actual_bytes = sum(int(row["size"]) for row in rows)
    if len(rows) != source.expected_files or actual_bytes != source.expected_bytes:
        raise ValueError(
            f"Official inventory drift for {source.directory}: got "
            f"{len(rows)} files/{actual_bytes} bytes; expected "
            f"{source.expected_files}/{source.expected_bytes}."
        )

    lines = [
        "# Generated by scripts/generate_themol_manifests.py from the official",
        "# ByteDance-Seed/THEMol sha256_ref.csv. Do not edit shard entries by hand.",
        f"# HuggingFace dataset commit: {HF_COMMIT}",
        "schema_version: 1",
        "kind: dataset",
        "namespace: themol",
        f"name: {source.name}",
        'version: "1"',
        "",
        f"title: {source.title}",
        "description: >-",
        *[f"  {line}" for line in source.description.splitlines()],
        "license: CC-BY-NC-4.0",
        "doi: 10.48550/arXiv.2605.14973",
        "",
        "artifacts:",
    ]
    for row in sorted(rows, key=_sort_key):
        relative = row["relative_path"]
        filename = Path(relative).name
        artifact_format = "csv" if filename.endswith(".csv") else "hdf5"
        lines.extend(
            [
                f"  - role: {_role(relative)}",
                f"    filename: {filename}",
                f"    format: {artifact_format}",
                f"    digest: sha256:{row['sha256']}",
                f"    size: {int(row['size'])}",
                "    locators:",
                f"      - hf://{SOURCE_REPOSITORY}@{HF_COMMIT}/{relative}",
                "",
            ]
        )
    lines.extend(
        [
            "targets:",
            f"  graph_level: {_yaml_list(source.graph_targets)}",
            f"  atom_level: {_yaml_list(source.atom_targets)}",
            "",
        ]
    )
    return "\n".join(lines)


def generate(inventory: Path, roots: list[Path]) -> None:
    with inventory.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required_columns = {"relative_path", "size", "sha256"}
    if not rows or not required_columns.issubset(rows[0]):
        raise ValueError(f"{inventory} is not a THEMol sha256_ref.csv inventory.")

    known_directories = {source.directory for source in SOURCES}
    found_directories = {row["relative_path"].split("/", 1)[0] for row in rows}
    if found_directories != known_directories:
        raise ValueError(
            f"Unexpected THEMol directories: found {sorted(found_directories)}, "
            f"expected {sorted(known_directories)}."
        )

    for source in SOURCES:
        selected = [
            row for row in rows if row["relative_path"].startswith(f"{source.directory}/")
        ]
        rendered = _render(source, selected)
        for root in roots:
            output = root / "dataset" / "themol" / source.name / "1.yaml"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered, encoding="utf-8")
            print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--root", type=Path, action="append", required=True)
    args = parser.parse_args()
    generate(args.inventory.resolve(), [root.resolve() for root in args.root])


if __name__ == "__main__":
    main()
