import type { RegistryArtifact } from "@/types/registry";

export const DIRECT_INSPECTION_LIMIT = 16 * 1024 * 1024;

export type MolvisFormat =
  | "pdb"
  | "xyz"
  | "cif"
  | "lammps"
  | "lammps-dump"
  | "sdf"
  | "dcd"
  | "cube"
  | "chgcar"
  | "gro"
  | "mol2"
  | "poscar"
  | "trr"
  | "xtc";

export type Inspectability =
  | {
      state: "direct";
      format: MolvisFormat;
      source: string;
      reason: string;
    }
  | {
      state: "derived";
      reason: string;
    }
  | {
      state: "unsupported";
      reason: string;
    };

const DIRECT_FORMATS: Readonly<Record<string, MolvisFormat>> = {
  chgcar: "chgcar",
  cif: "cif",
  cube: "cube",
  dcd: "dcd",
  extxyz: "xyz",
  gro: "gro",
  lammps: "lammps",
  "lammps-dump": "lammps-dump",
  mol2: "mol2",
  pdb: "pdb",
  poscar: "poscar",
  sdf: "sdf",
  trr: "trr",
  xtc: "xtc",
  xyz: "xyz",
};

const MEDIA_TYPE_FORMATS: Readonly<Record<string, MolvisFormat>> = {
  "chemical/x-cif": "cif",
  "chemical/x-mdl-sdfile": "sdf",
  "chemical/x-pdb": "pdb",
  "chemical/x-xyz": "xyz",
};

const DERIVED_FORMATS = new Set(["molrec-zarr-v3", "npz", "tar", "tar-bz2", "psmiles-csv"]);

/**
 * Decide whether an artifact can enter Inspector from declared byte semantics.
 * Filenames are deliberately ignored: an Inspect button is a promise that the
 * registry contract can support, not a guess based on a suffix.
 */
export function inspectability(artifact: RegistryArtifact): Inspectability {
  const declaredFormat = artifact.format?.toLowerCase() ?? null;
  const format =
    (declaredFormat ? DIRECT_FORMATS[declaredFormat] : undefined) ??
    (artifact.media_type ? MEDIA_TYPE_FORMATS[artifact.media_type.toLowerCase()] : undefined);

  if (format) {
    const source = artifact.locators.find(isHttpSource);
    if (!source) {
      return {
        state: "unsupported",
        reason: "Inspector needs an approved HTTPS source for this artifact.",
      };
    }
    if (artifact.size !== null && artifact.size > DIRECT_INSPECTION_LIMIT) {
      return {
        state: "derived",
        reason: `The declared ${declaredFormat ?? artifact.media_type} file is too large for the bounded direct path and needs a derived record.`,
      };
    }
    return {
      state: "direct",
      format,
      source,
      reason: `MolVis supports the declared ${declaredFormat ?? artifact.media_type} bytes directly.`,
    };
  }

  if (declaredFormat && DERIVED_FORMATS.has(declaredFormat)) {
    return {
      state: "derived",
      reason: `${declaredFormat} requires a traceable MolRec-derived inspection record.`,
    };
  }

  if (!declaredFormat && !artifact.media_type) {
    return {
      state: "unsupported",
      reason: "The manifest does not declare a format or media type.",
    };
  }

  return {
    state: "unsupported",
    reason: `Inspector has no reader for ${declaredFormat ?? artifact.media_type}.`,
  };
}

function isHttpSource(locator: string): boolean {
  try {
    const protocol = new URL(locator).protocol;
    return protocol === "https:" || protocol === "http:";
  } catch {
    return false;
  }
}
