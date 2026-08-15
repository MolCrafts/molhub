#!/usr/bin/env python3
"""Audit real, MolHub-fetched THEMol shards without flattening task groups."""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np

from molhub.dataset import (
    THEMolHessian,
    THEMolHessianRelax,
    THEMolMBIS,
    THEMolTorsionRelax,
    THEMolTorsionScan,
)
from molhub.dataset.themol import THEMOL_UNITS

DEFINITIONS = {
    "hessian": THEMolHessian,
    "hessian-relax": THEMolHessianRelax,
    "torsion-scan": THEMolTorsionScan,
    "torsion-relax": THEMolTorsionRelax,
    "mbis": THEMolMBIS,
}

# The MBIS atom columns whose names the format fixes; the Slater parameters are
# ``mbis_parameter_<slot>`` and their count is the shard's, so they are counted
# rather than listed (see :class:`molhub.dataset.themol.THEMolMBIS`).
_MBIS_COLUMNS = frozenset(THEMolMBIS.TARGET_SCHEMA.atom_level)
_PARAMETER_PREFIX = "mbis_parameter_"

# The scanned dihedral's 1-row block, as `molhub.dataset.themol` writes it.
_SCAN_COLUMNS = ("atomi", "atomj", "atomk", "atoml")


def _is_parameter(name: str) -> bool:
    """Whether *name* is one of the numbered per-atom Slater parameter columns."""
    return name.startswith(_PARAMETER_PREFIX) and name[len(_PARAMETER_PREFIX) :].isdigit()


def _indices(length: int, count: int) -> list[int]:
    if length <= count:
        return list(range(length))
    return sorted({int(value) for value in np.linspace(0, length - 1, count)})


def _finite(name: str, value: Any) -> None:
    array = np.asarray(value)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} contains NaN or Inf")


def _frame_audit(frame: Any) -> dict[str, Any]:
    atoms = frame["atoms"]
    numbers = np.asarray(atoms["number"])
    coords = np.stack([np.asarray(atoms[key]) for key in ("x", "y", "z")], axis=-1)
    _finite("coordinates", coords)
    if numbers.ndim != 1 or coords.shape != (len(numbers), 3):
        raise ValueError(
            f"atom/coordinate shape mismatch: Z={numbers.shape}, coords={coords.shape}"
        )
    meta = frame.meta
    if not meta.get("molecule_id") or not meta.get("source_id"):
        raise ValueError("frame is missing molecule_id or source_id provenance")
    result = {
        "n_atoms": int(len(numbers)),
        "molecule_id": str(meta["molecule_id"]),
        "source_id": str(meta["source_id"]),
        "total_charge": int(meta["total_charge"]),
    }
    if "energy" in meta:
        _finite("energy", float(meta["energy"]))
        forces = np.stack([np.asarray(atoms[key]) for key in ("fx", "fy", "fz")], axis=-1)
        _finite("forces", forces)
        if forces.shape != coords.shape:
            raise ValueError(f"coordinate/force shape mismatch: {coords.shape} != {forces.shape}")
    return result


def _audit_record(role: str, record: Any) -> dict[str, Any]:
    """Audit one record — a molpy ``Frame``, or a ``Trajectory`` of them.

    Every payload the deleted record dataclasses used to hold is read off the
    molpy object now: the Cartesian Hessian is the frame's ``hessian`` block, the
    MBIS supervision is ``atoms`` columns, and a trajectory's scalars are in each
    frame's own ``meta``.
    """
    if role == "hessian":
        frame_result = _frame_audit(record)
        block = record["hessian"]
        value = np.asarray(block["value"])
        _finite("hessian", value)
        expected = (3 * frame_result["n_atoms"]) ** 2
        if value.shape != (expected,):
            raise ValueError(f"unexpected Hessian entry count {value.shape}, expected {expected}")
        for name in ("row", "col"):
            if np.asarray(block[name]).shape != (expected,):
                raise ValueError(f"Hessian {name} index count disagrees with its values")
        return {**frame_result, "n_configurations": 1}

    if role == "mbis":
        frame_result = _frame_audit(record)
        atoms = record["atoms"]
        columns = [name for name in atoms.keys() if name in _MBIS_COLUMNS or _is_parameter(name)]
        missing = sorted(_MBIS_COLUMNS - set(columns))
        if missing:
            raise ValueError(f"MBIS frame is missing atom column(s) {missing}")
        for name in columns:
            _finite(name, np.asarray(atoms[name]))
        charge = np.asarray(atoms["atomic_charge"])
        if charge.shape != (frame_result["n_atoms"],):
            raise ValueError("MBIS charge count does not match atom count")
        return {
            **frame_result,
            "n_configurations": 1,
            "n_mbis_parameters": sum(1 for name in columns if _is_parameter(name)),
            "mbis_charge_sum_error": float(charge.sum()) - frame_result["total_charge"],
        }

    frames = list(record)
    if not frames:
        raise ValueError(f"{role} record contains no configurations")
    checked_indices = _indices(len(frames), 3)
    frame_results = [_frame_audit(frames[index]) for index in checked_indices]
    molecule_ids = {item["molecule_id"] for item in frame_results}
    if len(molecule_ids) != 1:
        raise ValueError(f"{role} group crosses molecular identities: {molecule_ids}")
    result = {
        "n_atoms": frame_results[0]["n_atoms"],
        "molecule_id": frame_results[0]["molecule_id"],
        "source_id": frame_results[0]["source_id"],
        "total_charge": frame_results[0]["total_charge"],
        "n_configurations": len(frames),
        "checked_configuration_indices": checked_indices,
    }
    if role.startswith("torsion"):
        scan_ids = {str(frames[index].meta["scan_id"]) for index in checked_indices}
        if len(scan_ids) != 1:
            raise ValueError(f"{role} group crosses scans: {scan_ids}")
        _finite(
            "torsion angles",
            [float(frames[index].meta["torsion_angle"]) for index in checked_indices],
        )
        scan = frames[0]["scan"]
        if [np.asarray(scan[name]).shape for name in _SCAN_COLUMNS] != [(1,)] * 4:
            raise ValueError("scanned dihedral is not one row of four atom indices")
        result["scan_id"] = scan_ids.pop()
        result["torsion_atom_indices"] = [int(np.asarray(scan[name])[0]) for name in _SCAN_COLUMNS]
    return result


def audit(role: str, path: Path, samples: int, *, head_only: bool) -> dict[str, Any]:
    definition = DEFINITIONS[role](path)
    shard_role = path.name if path.name.startswith("shard-") else "shard-000"
    if head_only:
        import h5py

        with h5py.File(path, "r") as handle:
            keys = list(itertools.islice(handle.keys(), samples))
            group_count = len(handle)
            records = [
                _audit_record(
                    role,
                    definition._READER(
                        handle,
                        key,
                        f"{definition.COORDINATE}#role={shard_role}",
                    ),
                )
                for key in keys
            ]
        chosen: list[int] = list(range(len(keys)))
    else:
        dataset = definition.load(role=shard_role)
        chosen = _indices(len(dataset), samples)
        records = [_audit_record(role, dataset[index]) for index in chosen]
        group_count = len(dataset)
    atom_counts = [record["n_atoms"] for record in records]
    configuration_counts = [record["n_configurations"] for record in records]
    return {
        "role": role,
        "coordinate": definition.COORDINATE,
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "groups_in_shard": group_count,
        "sampling": "head" if head_only else "evenly-spaced",
        "sample_indices": chosen,
        "sampled_groups": len(records),
        "sampled_configurations": sum(configuration_counts),
        "min_atoms": min(atom_counts),
        "max_atoms": max(atom_counts),
        "min_configurations_per_group": min(configuration_counts),
        "max_configurations_per_group": max(configuration_counts),
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        metavar="ROLE=PATH",
        help=f"Repeat for roles: {', '.join(DEFINITIONS)}",
    )
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument(
        "--head-only",
        action="store_true",
        help="Bound metadata IO by auditing the first groups instead of indexing the shard.",
    )
    args = parser.parse_args()
    if args.samples <= 0:
        parser.error("--samples must be positive")

    sources: list[tuple[str, Path]] = []
    for value in args.source:
        role, separator, raw_path = value.partition("=")
        if not separator or role not in DEFINITIONS:
            parser.error(f"invalid --source {value!r}")
        path = Path(raw_path).expanduser()
        if not path.is_file():
            parser.error(f"source path is not a file: {path}")
        sources.append((role, path))

    report = {
        "schema_version": 1,
        "status": "pass",
        "units": THEMOL_UNITS,
        "sources": [
            audit(role, path, args.samples, head_only=args.head_only) for role, path in sources
        ],
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
