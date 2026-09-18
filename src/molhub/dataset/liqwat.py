"""LIQWAT: itinerant polarization and Wannier centers for liquid water.

Reference:
    Knijff L., Zhang C., "Machine learning inference of molecular dipole moment
    in liquid water", Mach. Learn.: Sci. Technol. **2** 03LT03 (2021).
    https://doi.org/10.1088/2632-2153/ac0123

This is an **electrostatics** dataset, not a potential-fitting one: the frames
carry dipoles, polarization and REPEAT charges, and **no energies or forces**.
A ``potential_model`` cannot be fitted on it, and nothing here can produce an
``e_dress`` — that baseline is a fit of total energy against composition, and
there is no total energy in these files.

The single upstream file is a 92 MiB tarball holding two directories:

* ``itinerant_polarization/`` — 19543 frames, 1 fs apart, of the CP2K/BLYP
  DFTMD trajectory. Each ``water_trajectory_<i>.dat`` is the atom count, the
  total dipole (``D_x D_y D_z D_tot``), the itinerant polarization
  (``D_tot/cell_volume``), the cell (``A B C cell_volume``), then one line per
  atom of element, x, y, z and its REPEAT charge.
* ``wannier_centers/`` — the first 126 frames with Wannier centers included,
  written as element (``X`` marks a centre), x, y, z.

Both are in **atomic units** (Bohr, e, e·Bohr), grouped molecule by molecule,
and the molecular gauge is used for the dipole and the polarization. The box is
cubic, 23.493123360 Bohr (12.4322 angstrom), with 64 water molecules.

No dedicated reader: consume with :func:`molhub.fetch` and unpack the tarball.
A reader would have to decide how to present 19543 single-frame files as one
sequence, which is a design question this manifest does not prejudge.
"""

from __future__ import annotations

from molhub.coordinate import Coordinate
from molhub.manifest import Artifact, Manifest, TargetDeclaration
from molhub.sources import Digest, Locator

COORDINATE = "dataset:molcrafts/liqwat@1"

MANIFEST = Manifest(
    coordinate=Coordinate.parse(COORDINATE),
    title="LIQWAT — itinerant polarization and Wannier centers for liquid water",
    description=(
        "64 water molecules in a cubic 23.493 Bohr box, from a CP2K/BLYP ab initio MD "
        "trajectory. 19543 frames sampled every 1 fs carry the total dipole moment, the "
        "itinerant polarization and per-atom REPEAT charges; a further 126 frames carry "
        "Wannier centers. Atomic units throughout. Electrostatics only -- the dataset "
        "has no energies and no forces."
    ),
    license="CC-BY-4.0",
    doi="10.5281/zenodo.4752246",
    artifacts={
        "main": Artifact(
            role="main",
            filename="LIQWAT_dataset.tar.gz",
            format="liqwat-tar",
            media_type="application/gzip",
            locators=(Locator.parse("zenodo://4752246/LIQWAT_dataset.tar.gz"),),
            digest=Digest.parse("md5:42250c6f3802ce9519e7d902cdbac9c0"),
            size=92_444_985,
        )
    },
    # The record id 4752246 is the published version; 4752245 is the concept DOI
    # that always resolves to the newest one and so cannot pin bytes.
    targets=TargetDeclaration(graph_level=("dipole", "polarization"), atom_level=("charges",)),
)
