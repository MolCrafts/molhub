"""Convert Espaloma's ``small_phalkethoh_mm.zip`` into the layout molhub reads.

``dataset:espaloma/phalkethoh-mm-small@1`` publishes a zip of DGL heterographs
(``u_ref`` in Hartree, 100 conformers per molecule), and
:class:`~molhub.dataset.phalkethoh_mm.PhalkethohMMDataset` reads a *converted*
tree that only this conversion produces::

    out/
      splits.json          # molecule-level 80/10/10, seed 2666 (Espaloma notebook)
      mols/<id>/
        atoms.npz          # number, atomi, atomj
        confs.npz          # coords (C, N, 3) Å, mm_energy (C,) kcal/mol
        legacy_params.json # optional bond/angle reference parameters

So the loader refuses that dataset and hands the reader this command::

    python -m molhub.scripts.convert_espaloma_phalkethoh_mm --src <zip> --out <dir>

A command that only exists in a git checkout is not one a pip-installed reader
can run, which is why the conversion ships **inside the wheel** rather than in
``scripts/`` beside it — the same promotion ``molhub.scripts.build_class1_splits``
already had, and the repository file is now a shim over this module.

**The conversion needs dgl, and molhub does not depend on it.** That is why it is
offline and once: dgl is not installable in most environments molhub runs in. The
arguments are therefore parsed **before** dgl is imported, so ``--help`` answers
in an environment that will never be able to run the conversion, and a run
without dgl states the package, the install line and the fact that nothing was
written — rather than raising ``ModuleNotFoundError`` three frames deep.

Reference:
    Espaloma MM-small notebook (shuffle seed 2666, split 8:1:1).
    Energy conversion: 1 Hartree = 627.5094740631 kcal/mol.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["HARTREE_TO_KCAL", "DEFAULT_SEED", "DEFAULT_RATIOS", "PhalkethohConversion", "main"]

#: How this converter is spelled everywhere a reader is told to run it: the
#: ``prog`` of its own parser and — mirrored as a literal, exactly as
#: ``molhub.scripts.build_class1_splits`` mirrors its own — the command the
#: loader's refusal for ``dataset:espaloma/phalkethoh-mm-small@1`` names. Written
#: out rather than read off ``__spec__``, which says ``__main__`` under some
#: launchers and is exactly the spelling a reader cannot type.
MODULE = "molhub.scripts.convert_espaloma_phalkethoh_mm"
COMMAND = f"python -m {MODULE}"

#: 1 Hartree in kcal/mol, hard-coded so a "cleanup" to a rounder constant shows
#: up as a failing test rather than as a silently shifted energy scale.
HARTREE_TO_KCAL = 627.5094740631

#: The Espaloma notebook's own shuffle seed. The split is only *the Espaloma
#: split* because the seed is theirs.
DEFAULT_SEED = 2666

#: train : val : test, molecule level.
DEFAULT_RATIOS = (0.8, 0.1, 0.1)

#: What the reader has to install, and the release line the conversion was
#: written against. "install dgl" with no version fails on the current release.
DGL_REQUIREMENT = "dgl==1.1.3"

# Where the published zip keeps one molecule's files, and what each is called.
_MEMBER_PREFIX = "phalkethoh/"
_GRAPH_MEMBER = "heterograph.bin"
_MOLECULE_MEMBER = "mol.json"


class PhalkethohConversion:
    """One conversion of the published zip into the tree the dataset reads.

    Args:
        source: The published ``small_phalkethoh_mm.zip``.
        output: Directory the converted tree is written into. Nothing under it
            is created until dgl has been resolved, so a refusal leaves no half
            a tree behind — one ``PhalkethohMMDataset`` would open happily and
            quietly under-report.
        seed: What fixes the molecule-level shuffle; the published default is
            :data:`DEFAULT_SEED`.
    """

    def __init__(self, source: Path, output: Path, *, seed: int = DEFAULT_SEED) -> None:
        self._source = Path(source)
        self._output = Path(output)
        self._seed = seed

    def run(self) -> dict[str, object]:
        """Write the converted tree and report what it holds.

        Returns:
            Molecule and conformer counts, the per-split molecule counts and the
            output directory — what the command prints as its own receipt.

        Raises:
            ImportError: If dgl is not importable. Raised before anything is
                created, so nothing was written.
            ValueError: If *source* holds no ``phalkethoh/`` entries, or a
                molecule's energies and conformers disagree in length.
        """
        dgl = self._dgl()
        with zipfile.ZipFile(self._source) as archive:
            identifiers = self._identifiers(archive)
            molecules = self._output / "mols"
            if molecules.exists():
                shutil.rmtree(molecules)
            molecules.mkdir(parents=True)
            scratch = self._output / "_dgl_tmp"
            scratch.mkdir(exist_ok=True)
            for identifier in identifiers:
                self._write_molecule(archive, identifier, dgl=dgl, scratch=scratch)
            shutil.rmtree(scratch, ignore_errors=True)
        splits = self._splits(identifiers)
        (self._output / "splits.json").write_text(json.dumps(splits, indent=2) + "\n")
        return {
            "n_molecules": len(identifiers),
            "n_conformers": len(identifiers) * 100,
            "split": {
                name: len(value) for name, value in splits.items() if isinstance(value, list)
            },
            "out": str(self._output),
        }

    @staticmethod
    def _dgl() -> Any:
        """The dgl module, or a refusal that says how to get it.

        Raises:
            ImportError: If dgl is not importable, naming the package, the
                release this conversion was written against and the fact that
                nothing was written.
        """
        try:
            import dgl
        except ImportError as error:
            raise ImportError(
                f"This conversion reads DGL heterographs and dgl is not importable here. "
                f"molhub does not depend on it, which is why the conversion is offline and "
                f"once: pip install '{DGL_REQUIREMENT}' in an environment whose Python it "
                f"supports, then re-run {COMMAND}. Nothing was written."
            ) from error
        return dgl

    def _identifiers(self, archive: zipfile.ZipFile) -> list[str]:
        """Every molecule id the published zip holds, sorted.

        Raises:
            ValueError: If the archive holds no ``phalkethoh/`` entries — it is
                not the published payload, and converting it would write an
                empty tree the dataset opens without complaint.
        """
        identifiers = sorted(
            {
                name.split("/")[1]
                for name in archive.namelist()
                if name.startswith(_MEMBER_PREFIX) and len(name.split("/")) >= 3
            }
        )
        if not identifiers:
            raise ValueError(
                f"{self._source} holds no {_MEMBER_PREFIX}* entries, so it is not the "
                "published small_phalkethoh_mm.zip. Nothing was written."
            )
        return identifiers

    def _write_molecule(
        self, archive: zipfile.ZipFile, identifier: str, *, dgl: Any, scratch: Path
    ) -> None:
        """Write one molecule's ``atoms.npz`` / ``confs.npz`` / legacy parameters.

        Args:
            archive: The open published zip.
            identifier: The molecule id, which is also its directory name.
            dgl: The resolved dgl module.
            scratch: Where one heterograph is unpacked at a time; dgl reads a
                path rather than bytes.

        Raises:
            ValueError: If this molecule's reference energies and its conformers
                do not agree in length.
        """
        member = archive.read(f"{_MEMBER_PREFIX}{identifier}/{_MOLECULE_MEMBER}")
        molecule = json.loads(json.loads(member))
        numbers = np.array([atom["atomic_number"] for atom in molecule["atoms"]], dtype=np.int64)
        atomi = np.array([bond["atom1"] for bond in molecule["bonds"]], dtype=np.int64)
        atomj = np.array([bond["atom2"] for bond in molecule["bonds"]], dtype=np.int64)

        graph_path = scratch / _GRAPH_MEMBER
        graph_path.write_bytes(archive.read(f"{_MEMBER_PREFIX}{identifier}/{_GRAPH_MEMBER}"))
        graphs, _ = dgl.load_graphs(str(graph_path))
        graph = graphs[0]
        xyz = graph.nodes["n1"].data["xyz"].detach().cpu().numpy()
        energies = graph.nodes["g"].data["u_ref"].detach().cpu().numpy().reshape(-1)
        if energies.shape[0] != xyz.shape[1]:
            raise ValueError(
                f"{identifier}: {energies.shape[0]} reference energies for {xyz.shape[1]} "
                "conformers. Nothing further was written."
            )

        directory = self._output / "mols" / identifier
        directory.mkdir()
        np.savez_compressed(directory / "atoms.npz", number=numbers, atomi=atomi, atomj=atomj)
        np.savez_compressed(
            directory / "confs.npz",
            coords=np.transpose(xyz, (1, 0, 2)).astype(np.float64),
            mm_energy=energies.astype(np.float64) * HARTREE_TO_KCAL,
        )
        legacy = self._legacy_parameters(graph)
        if legacy:
            (directory / "legacy_params.json").write_text(json.dumps(legacy))

    @staticmethod
    def _legacy_parameters(graph: Any) -> dict[str, list[object]]:
        """The bond and angle reference parameters the graph carries, if any.

        They are the upstream MM assignment rather than a target, so a molecule
        without them is written without the file instead of with an empty one.
        """
        legacy: dict[str, list[object]] = {}
        for node, prefix in (("n2", "bond"), ("n3", "angle")):
            if not graph.num_nodes(node) or "k_ref" not in graph.nodes[node].data:
                continue
            data = graph.nodes[node].data
            legacy[f"{prefix}_k_ref"] = data["k_ref"].detach().cpu().numpy().reshape(-1).tolist()
            legacy[f"{prefix}_eq_ref"] = data["eq_ref"].detach().cpu().numpy().reshape(-1).tolist()
            legacy[f"{prefix}_idxs"] = data["idxs"].detach().cpu().numpy().astype(int).tolist()
        return legacy

    def _splits(self, identifiers: Sequence[str]) -> dict[str, object]:
        """The molecule-level 80/10/10 assignment, seeded as Espaloma seeds it."""
        shuffled = list(identifiers)
        random.Random(self._seed).shuffle(shuffled)
        total = len(shuffled)
        n_train = int(total * DEFAULT_RATIOS[0])
        n_val = int(total * DEFAULT_RATIOS[1])
        return {
            "train": shuffled[:n_train],
            "val": shuffled[n_train : n_train + n_val],
            "test": shuffled[n_train + n_val :],
            "seed": self._seed,
            "ratios": list(DEFAULT_RATIOS),
            "scheme": "espaloma-original",
        }


def main(argv: Sequence[str] | None = None) -> int:
    """Convert the published zip into the tree ``PhalkethohMMDataset`` reads.

    Arguments are parsed before dgl is imported, so ``--help`` answers in an
    environment that cannot run the conversion — which is the environment most
    readers meeting the loader's refusal are in.

    Args:
        argv: Command-line arguments; ``None`` reads :data:`sys.argv`.

    Returns:
        ``0`` when the tree was written, ``1`` when it could not be — dgl is not
        importable, or the source is not the published payload. A code rather
        than an exception, as the shipped split generator already does: one
        shape for one job is what makes ``python -m`` predictable.
    """
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--src", type=Path, required=True, help="The published small_phalkethoh_mm.zip."
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="Directory to write the converted tree into."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Molecule-level shuffle seed; the published one is {DEFAULT_SEED}.",
    )
    args = parser.parse_args(argv)

    try:
        report = PhalkethohConversion(args.src, args.out, seed=args.seed).run()
    except (ImportError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
