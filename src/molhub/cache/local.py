"""Where a mutable cache is allowed to live.

Shared filesystem = source data and immutable snapshots.
Node-local filesystem = the mutable runtime cache.

A live LMDB is a writable mmap plus its own POSIX lock table (``lock=True``).
On Lustre a second process blocks forever in ``F_SETLKW``
(``ldlm_flock_completion_ast``), and the mapping is not coherent across
processes. The same is true of NFS and of an ``fcntl.flock`` file. Opening a
mutable cache on those filesystems is refused. Workers on one node share the
path and each open their own environment after they start; the environment
is not inherited from the parent.

``/scratch/local`` is node-local scratch (on Arrhenius, the NVMe reserved
for one job on that node). A job on several nodes therefore has one cache
per node, not one cache shared through the scratch path. A snapshot that
should outlive the job is an immutable file on the shared filesystem,
copied onto this root at start and written back only after every handle
is closed. It is not opened in place.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

_NETWORK = frozenset(
    {
        "lustre",
        "nfs",
        "nfs4",
        "gpfs",
        "beegfs",
        "ceph",
        "cifs",
        "smb",
        "smb2",
        "smb3",
        "fuse.sshfs",
        "9p",
        "afs",
        "pvfs2",
        "panfs",
    }
)

# First well-known node-local scratch. Absent on a login node; present on
# Arrhenius compute nodes.
_NODE_SCRATCH = Path("/scratch/local")


def cache_write_failed(error: BaseException) -> bool:
    """True when a node-local cache write died because the disk did.

    A full scratch comes back as ``ENOSPC`` from a plain file and, from LMDB,
    as ``mdb_txn_commit: Input/output error``. Either one means "stop writing",
    not "abort the training step".
    """
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EIO, errno.EDQUOT):
        return True
    text = str(error).lower()
    return (
        "no space left" in text
        or "input/output error" in text
        or "mdb_map_full" in text
        or "disk quota" in text
    )


_POLICY = (
    "Shared filesystems hold source data and immutable snapshots. "
    "A mutable runtime cache stays on node-local disk."
)


def fstype(path: Path) -> str:
    """Filesystem type of *path*, from ``/proc/mounts``.

    The longest matching mount wins. A missing path is probed through the
    nearest existing ancestor. An unreadable mount table yields ``""``.
    """
    target = os.path.realpath(path)
    best = -1
    found = ""
    try:
        lines = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        mount = (
            parts[1]
            .replace("\\040", " ")
            .replace("\\011", "\t")
            .replace("\\012", "\n")
            .replace("\\134", "\\")
        )
        if target == mount or target.startswith(mount.rstrip("/") + "/"):
            if len(mount) > best:
                best = len(mount)
                found = parts[2]
    return found


def on_shared_filesystem(path: Path | str) -> bool:
    """True when *path* is on a filesystem whose locks and mmap do not hold."""
    kind = fstype(_existing(Path(path)))
    return kind in _NETWORK or kind.startswith("nfs")


def _existing(path: Path) -> Path:
    probe = path.expanduser().resolve()
    if probe.exists():
        return probe
    probe = probe.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def require_node_local(path: Path | str) -> Path:
    """*path* when it is node-local.

    Raises:
        RuntimeError: *path* is on a shared filesystem. The mutable cache is
            not moved and no other lock is substituted.
    """
    asked = Path(path)
    kind = fstype(_existing(asked))
    if kind in _NETWORK or kind.startswith("nfs"):
        raise RuntimeError(f"{asked} is on {kind}. {_POLICY}")
    return asked


def runtime_cache_root() -> Path:
    """Directory for this process's mutable caches. Not created here.

    ``$MOLHUB_RUNTIME_CACHE`` when set. Otherwise
    ``/scratch/local/molcache/$SLURM_JOB_ID`` when that scratch is
    node-local (``user-<uid>`` outside a job). Otherwise
    ``$SLURM_TMPDIR/molcache`` when that directory is node-local, otherwise
    ``/tmp/molcache/<same leaf>``.

    Raises:
        RuntimeError: The chosen directory is on a shared filesystem, or no
            node-local candidate exists.
    """
    override = (os.environ.get("MOLHUB_RUNTIME_CACHE") or "").strip()
    if override:
        root = Path(override).expanduser()
        kind = fstype(_existing(root))
        if kind in _NETWORK or kind.startswith("nfs"):
            raise RuntimeError(f"MOLHUB_RUNTIME_CACHE={root} is on {kind}. {_POLICY}")
        return root
    leaf = (os.environ.get("SLURM_JOB_ID") or "").strip() or f"user-{os.getuid()}"
    scratch = _NODE_SCRATCH
    if scratch.is_dir() and not on_shared_filesystem(scratch):
        return scratch / "molcache" / leaf
    tmpdir = (os.environ.get("SLURM_TMPDIR") or "").strip()
    if tmpdir and not on_shared_filesystem(Path(tmpdir)):
        return Path(tmpdir) / "molcache"
    tmp = Path("/tmp")
    if not on_shared_filesystem(tmp):
        return tmp / "molcache" / leaf
    raise RuntimeError(f"No node-local directory for a mutable cache. {_POLICY}")
