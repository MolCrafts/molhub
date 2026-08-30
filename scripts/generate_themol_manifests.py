#!/usr/bin/env python3
"""Generate THEMol Python catalog entries from its official inventory.

The input is ByteDance-Seed/THEMol's ``moleculedataset/tests/sha256_ref.csv``.
Generation is deliberately strict: it accepts only the reviewed five-subset
inventory and writes ``src/molhub/dataset/themol_files.py``.
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
        # The atoms columns whose names the MBIS format fixes. The MBIS Slater
        # shells are deliberately absent: the source `parameters` array is one
        # row per *shell*, not per atom (probed 2026-08-15 on the real published
        # mbis shard-000 — shells per atom vary, so S > N), so the reader emits
        # them as the `mbis_shells` block and no atom-level target can name
        # them. The `THEMolMBIS` docstring in src/molhub/dataset/themol.py is
        # the authority for this list.
        atom_targets=(
            "atomic_charge",
            "atomic_volume",
            "dipole_x",
            "dipole_y",
            "dipole_z",
            "quadrupole_xx",
            "quadrupole_xy",
            "quadrupole_xz",
            "quadrupole_yx",
            "quadrupole_yy",
            "quadrupole_yz",
            "quadrupole_zx",
            "quadrupole_zy",
            "quadrupole_zz",
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


def _render_python(sources_and_rows: list[tuple[Source, list[dict[str, str]]]]) -> str:
    lines = [
        "# ruff: noqa: E501",
        '"""THEMol downloadable files. Generated from the official inventory.',
        "",
        "Do not edit shard rows by hand. Regenerate with",
        "``scripts/generate_themol_manifests.py``.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from molhub.coordinate import Coordinate",
        "from molhub.manifest import Artifact, Manifest, TargetDeclaration",
        "from molhub.sources import Digest, Locator",
        "",
        f"HF_COMMIT = {HF_COMMIT!r}",
        f"SOURCE_REPOSITORY = {SOURCE_REPOSITORY!r}",
        "",
        "",
        "def _artifact(",
        "    role: str, filename: str, digest: str, size: int, relative: str",
        ") -> Artifact:",
        '    kind = "csv" if filename.endswith(".csv") else "hdf5"',
        "    return Artifact(",
        "        role=role,",
        "        filename=filename,",
        "        format=kind,",
        '        locators=(Locator.parse(f"hf://{SOURCE_REPOSITORY}@{HF_COMMIT}/{relative}"),),',
        "        digest=Digest.parse(digest),",
        "        size=size,",
        "    )",
        "",
    ]
    names: list[str] = []
    for source, rows in sources_and_rows:
        actual_bytes = sum(int(row["size"]) for row in rows)
        if len(rows) != source.expected_files or actual_bytes != source.expected_bytes:
            raise ValueError(
                f"Official inventory drift for {source.directory}: got "
                f"{len(rows)} files/{actual_bytes} bytes; expected "
                f"{source.expected_files}/{source.expected_bytes}."
            )
        ident = source.name.replace("-", "_").upper()
        names.append(ident)
        files_name = f"_{ident}_FILES"
        lines.append(f"{files_name}: tuple[tuple[str, str, str, int, str], ...] = (")
        for row in sorted(rows, key=_sort_key):
            relative = row["relative_path"]
            filename = Path(relative).name
            lines.append(
                f"    ({_role(relative)!r}, {filename!r}, "
                f"'sha256:{row['sha256']}', {int(row['size'])}, {relative!r}),"
            )
        lines.extend(
            [
                ")",
                "",
                f"{ident} = Manifest(",
                f'    coordinate=Coordinate.parse("dataset:themol/{source.name}@1"),',
                f"    title={source.title!r},",
                f"    description={source.description!r},",
                '    license="CC-BY-NC-4.0",',
                '    doi="10.48550/arXiv.2605.14973",',
                "    artifacts={",
                "        role: _artifact(role, filename, digest, size, relative)",
                f"        for role, filename, digest, size, relative in {files_name}",
                "    },",
                "    targets=TargetDeclaration(",
                f"        graph_level={source.graph_targets!r},",
                f"        atom_level={source.atom_targets!r},",
                "    ),",
                ")",
                "",
            ]
        )
    lines.append(f"MANIFESTS = ({', '.join(names)},)")
    lines.append("")
    return "\n".join(lines)


def generate(inventory: Path, output: Path) -> None:
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

    selected = [
        (
            source,
            [row for row in rows if row["relative_path"].startswith(f"{source.directory}/")],
        )
        for source in SOURCES
    ]
    output.write_text(_render_python(selected), encoding="utf-8")
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src/molhub/dataset/themol_files.py",
    )
    args = parser.parse_args()
    generate(args.inventory.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
