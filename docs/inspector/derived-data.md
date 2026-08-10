# Derived data

Archives, NPZ files, and very large trajectories are converted by a trusted job into a MolRec/Zarr
record. Its descriptor records source coordinate, role, digest, size, converter version and commit,
MolRec schema version, generation time, frame count, and property targets.

Derived keys are computed from immutable source and converter inputs. Rebuilding may produce a new URL
and timestamp but the same identity. Changing source bytes or converter version creates a new key;
there is no mutable `latest` output.

The derived store is a disposable preview cache, not the registry authority. HTTP range/chunk readers
must abort, reject corrupt ranges, and refuse an unbounded full-body fallback.
