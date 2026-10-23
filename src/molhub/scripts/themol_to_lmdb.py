"""Write one THEMol HDF5 shard as a molrec LMDB collection.

Each record is split by :meth:`~molhub.dataset.themol.THEMolShardDataset.split`
into its system (identity and topology, written once) and its frames (state,
one row each), on molrec's conventions. The collection index carries each
record's molecule code, element mask and upstream key, so a reader sizes and
splits the collection without decoding a record.

Reading HDF5 is the slow part (hundreds of ms per record), so records are split
in worker processes and written, in order, by this one.

Usage::

    python -m molhub.scripts.themol_to_lmdb THEMolHessianRelax shard-000 OUT.mrec.lmdb \\
        [--workers 32] [--limit N]
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

from molhub.dataset import themol
from molhub.io.lmdb import Lmdb
from molhub.io.mrec import MrecWriter

#: THEMol's per-target units, re-keyed by molrec quantity.
_QUANTITY = {"coordinates": "length", "energy": "energy", "forces": "force", "charge": "charge"}

_DATASET: Any = None


def _open(definition: str, role: str) -> None:
    global _DATASET
    _DATASET = getattr(themol, definition)().load(role)


def _plain(frame: Any) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """A Frame as numpy columns and meta — what may cross a process boundary.

    A molpy Frame is a molrs object that must stay on the thread that made it,
    and ``Pool`` unpickles results on a thread of its own, so frames are
    rebuilt in the writing thread instead of shipped.
    """
    import numpy as np

    blocks = {
        name: {column: np.asarray(frame[name][column]) for column in frame[name].keys()}
        for name in frame.keys()
    }
    return blocks, {k: getattr(v, "value", v) for k, v in frame.meta.items()}


def _frame(plain: tuple[dict[str, dict[str, Any]], dict[str, Any]]) -> Any:
    from molpy import Block, Frame

    blocks, meta = plain
    frame = Frame()
    for name, columns in blocks.items():
        frame[name] = Block(columns)
    frame.meta = meta
    return frame


def _split(index: int) -> tuple[int, Any]:
    system, frames, steps = _DATASET.split(index)
    return index, (_plain(system), [_plain(f) for f in frames], steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("definition", help="THEMol definition class, e.g. THEMolHessianRelax")
    parser.add_argument("role", help="shard role, e.g. shard-000")
    parser.add_argument("out", type=Path, help="collection file to create (*.mrec.lmdb)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0, help="convert only the first N records")
    args = parser.parse_args(argv)

    source = getattr(themol, args.definition)().load(args.role)
    n = len(source) if not args.limit else min(args.limit, len(source))
    molecules = source.molecule_index()
    masks = source.element_mask()
    keys = source.keys()
    # Every THEMol frame carries coordinates in Å, whether or not a task's
    # declaration lists them; the collection states it.
    units = {"length": themol.THEMOL_UNITS["coordinates"]}
    units.update(
        {_QUANTITY[t]: unit for t, unit in source.manifest.units.items() if t in _QUANTITY}
    )
    meta = {"source_id": source.source_id, "coordinate": str(source.manifest.coordinate)}
    started = time.perf_counter()
    with MrecWriter(args.out, backend=Lmdb, units=units, meta=meta) as out:
        if args.workers > 1:
            context = mp.get_context("spawn")
            with context.Pool(
                args.workers, initializer=_open, initargs=(args.definition, args.role)
            ) as pool:
                records = pool.imap(_split, range(n), chunksize=8)
                for done, (i, (system, frames, steps)) in enumerate(records, 1):
                    out.write_record(
                        [_frame(f) for f in frames],
                        system=_frame(system),
                        steps=steps,
                        index={
                            "molecule": int(molecules[i]),
                            "element_mask": int(masks[i]),
                            "record_id": str(keys[i]),
                        },
                    )
                    if done % 2000 == 0:
                        rate = done / (time.perf_counter() - started)
                        print(f"{done}/{n} records, {rate:.1f}/s", flush=True)
        else:
            for i in range(n):
                system, frames, steps = source.split(i)
                out.write_record(
                    frames,
                    system=system,
                    steps=steps,
                    index={
                        "molecule": int(molecules[i]),
                        "element_mask": int(masks[i]),
                        "record_id": str(keys[i]),
                    },
                )
    elapsed = time.perf_counter() - started
    print(f"wrote {n} records to {args.out} in {elapsed:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
