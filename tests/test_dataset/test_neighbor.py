"""Tests for the neighbour delegate — a thin wrapper over ``molix.batch.NeighborList``.

MolHub must not own a second neighbour-list implementation. The kernel-output
normalisation (PBC, NaN-padding strip, symmetry expansion, edge-sign negation)
lives in molnex, and the delegate's whole job is to forward to it, so the
dependency runs molhub -> molnex and never the other way.

Two things are therefore pinned here:

1. **Pass-through.** With a recording stand-in injected at the delegate's one
   seam, the delegate must return exactly what the wrapped list returned and
   must not touch the sample on the way in or the edge tensors on the way out.
   These tests run with no molnex install, which also forces the ``molix``
   import to stay lazy — a module-level ``from molix.batch.neighbor import …``
   would make this whole file unimportable in molhub's own environment.
2. **Numerical identity.** On a 3-atom chain, the delegate reproduces
   ``molix.batch.NeighborList``'s ``edge_index`` / ``edge_diff`` / ``edge_dist``
   exactly. The expected values are embedded as hard-coded goldens (see
   ``_GOLDEN_*`` below), so no live oracle runs at test time; the identity test
   against the real class runs only where molnex is installed.

Edge convention (molnex, ``CLAUDE.md`` §"Edge Convention"):
``edge_index[:, 0]`` is the source, ``edge_index[:, 1]`` the target, and
``edge_diff = pos[target] - pos[source]``.
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
from pathlib import Path

import pytest

from molhub.dataset.neighbor import NeighborDelegate

# ---------------------------------------------------------------------------
# The 3-atom chain and its goldens
# ---------------------------------------------------------------------------

#: Collinear chain along x: bonded pair at 1.0 Å, a second gap of 1.5 Å.
_CHAIN_POS: tuple[tuple[float, float, float], ...] = (
    (0.0, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (2.5, 0.0, 0.0),
)
_CHAIN_Z: tuple[int, ...] = (1, 1, 1)
_CUTOFF = 2.0

# Goldens produced offline from the reference implementation — no oracle runs
# at test time.
#   tool:    molnex molix.batch.NeighborList (branch feat/mm-param-val, 2026-08-14)
#   runtime: torch 2.12.1+cpu, Python 3.14
#   command: NeighborList(cutoff=2.0).execute({"Z": tensor([1,1,1]), "pos": tensor(_CHAIN_POS)})
#   date:    2026-08-14
#
# With the default ``symmetry=True`` the kernel's two half-pairs are followed by
# their reverses, so E = 2 * n_pairs = 4 and the reversed block carries the
# sign-flipped displacement.
_GOLDEN_EDGE_INDEX: tuple[tuple[int, int], ...] = ((1, 0), (2, 1), (0, 1), (1, 2))
_GOLDEN_EDGE_DIFF: tuple[tuple[float, float, float], ...] = (
    (-1.0, 0.0, 0.0),
    (-1.5, 0.0, 0.0),
    (1.0, 0.0, 0.0),
    (1.5, 0.0, 0.0),
)
_GOLDEN_EDGE_DIST: tuple[float, ...] = (1.0, 1.5, 1.0, 1.5)
_GOLDEN_TASK_ID = "nlist:cut=2.0:max=512:pbc=False:sym=True"

#: Half-pair mode (``symmetry=False``): only the upper-triangle pairs survive.
_GOLDEN_HALF_EDGE_INDEX: tuple[tuple[int, int], ...] = ((1, 0), (2, 1))
_GOLDEN_HALF_TASK_ID = "nlist:cut=2.0:max=512:pbc=False:sym=False"

#: Displacements and distances are lengths in Å, so both are pinned at the
#: position tolerance rather than an energy one.
_POS_ATOL = 1e-12


# ---------------------------------------------------------------------------
# molnex availability
# ---------------------------------------------------------------------------


def _molix_neighbor_list() -> type:
    """Return ``molix.batch.NeighborList``, or skip when molnex is absent.

    molnex is an optional peer of molhub: only :mod:`molhub.dataset.neighbor`
    needs it, so it belongs in an extra rather than in the base dependency set
    (the same treatment ``huggingface_hub`` gets). Setting ``MOLNEX_SRC`` to a
    molnex checkout's ``src`` directory is the escape hatch for an environment
    that has torch but no installed molnex.
    """
    src = os.environ.get("MOLNEX_SRC")
    if src and src not in sys.path:
        sys.path.insert(0, src)
    try:
        return importlib.import_module("molix.batch.neighbor").NeighborList
    except ImportError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            "molnex (molix) is not importable: "
            f"{exc}. Install the molhub extra that pulls molnex, or point "
            "MOLNEX_SRC at a molnex checkout's src/ directory."
        )


def _tensor_pos() -> object:
    """The chain positions as a torch tensor, for the real molix path."""
    torch = pytest.importorskip("torch")
    return torch.tensor(_CHAIN_POS, dtype=torch.float32)


# ---------------------------------------------------------------------------
# Recording stand-in for the wrapped list
# ---------------------------------------------------------------------------


class RecordingNeighborList:
    """Stands in for ``molix.batch.NeighborList`` at the delegate's seam.

    Mirrors the structural contract molnex documents for that class — a
    ``task_id`` and an ``execute`` — and nothing else, so a delegate that
    reaches for anything more fails here rather than in production.
    """

    def __init__(self, task_id: str = "nlist:fake") -> None:
        self.task_id = task_id
        self.calls: list[dict[str, object]] = []
        self.returned: dict[str, object] = {}

    def execute(self, data: dict[str, object]) -> dict[str, object]:
        self.calls.append(data)
        self.returned = {
            **data,
            "edge_index": object(),
            "edge_diff": object(),
            "edge_dist": object(),
        }
        return self.returned


def _sample() -> dict[str, object]:
    return {"Z": _CHAIN_Z, "pos": _CHAIN_POS}


# ---------------------------------------------------------------------------
# Pass-through — runs without molnex installed
# ---------------------------------------------------------------------------


class TestNeighborDelegatePassThrough:
    def test_returns_the_wrapped_output_object(self):
        """No re-wrapping, no copying: the delegate hands the result back."""
        inner = RecordingNeighborList()
        out = NeighborDelegate(cutoff=_CUTOFF, neighbor_list=inner).execute(_sample())
        assert out is inner.returned

    def test_edge_tensors_are_the_wrapped_ones(self):
        """A delegate that recomputed anything would not pass identity here."""
        inner = RecordingNeighborList()
        out = NeighborDelegate(cutoff=_CUTOFF, neighbor_list=inner).execute(_sample())
        for key in ("edge_index", "edge_diff", "edge_dist"):
            assert out[key] is inner.returned[key]

    def test_the_wrapped_list_is_called_once(self):
        inner = RecordingNeighborList()
        NeighborDelegate(cutoff=_CUTOFF, neighbor_list=inner).execute(_sample())
        assert len(inner.calls) == 1

    def test_the_sample_is_forwarded_unmodified(self):
        inner = RecordingNeighborList()
        sample = _sample()
        NeighborDelegate(cutoff=_CUTOFF, neighbor_list=inner).execute(sample)
        assert inner.calls[0]["pos"] == _CHAIN_POS
        assert inner.calls[0]["Z"] == _CHAIN_Z

    def test_call_is_an_alias_of_execute(self):
        inner = RecordingNeighborList()
        delegate = NeighborDelegate(cutoff=_CUTOFF, neighbor_list=inner)
        assert delegate(_sample()) is inner.returned

    def test_task_id_is_the_wrapped_task_id(self):
        """Cache identity is delegated too, or two caches disagree silently."""
        inner = RecordingNeighborList(task_id="nlist:cut=2.0:max=512:pbc=False:sym=True")
        delegate = NeighborDelegate(cutoff=_CUTOFF, neighbor_list=inner)
        assert delegate.task_id == "nlist:cut=2.0:max=512:pbc=False:sym=True"


class TestNeighborDelegateDoesNotDuplicate:
    """ac-006: the normalisation lives in molnex and is never copied here."""

    @staticmethod
    def _code() -> str:
        """The module's executable code, with docstrings and comments removed.

        Prose that *names* the operations molnex owns is exactly what this
        module should contain; only re-implementing them is forbidden.
        """
        module = importlib.import_module("molhub.dataset.neighbor")
        assert module.__file__ is not None
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if not isinstance(body, list) or not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                body.pop(0)
        return ast.unparse(tree)

    @pytest.mark.parametrize(
        "forbidden",
        [
            "isnan",  # NaN-padding strip
            "cdist",  # pair enumeration
            "-deltas",  # edge-sign negation
            "cat(",  # symmetry expansion
        ],
    )
    def test_module_contains_no_reimplementation(self, forbidden):
        assert forbidden not in self._code()

    def test_module_names_the_class_it_delegates_to(self):
        assert "NeighborList" in self._code()


# ---------------------------------------------------------------------------
# Numerical identity on the 3-atom chain — hard-coded goldens
# ---------------------------------------------------------------------------


class TestNeighborDelegateGoldens:
    def test_edge_index_matches_the_golden(self):
        _molix_neighbor_list()
        out = NeighborDelegate(cutoff=_CUTOFF).execute({"Z": _CHAIN_Z, "pos": _tensor_pos()})
        assert [tuple(row) for row in out["edge_index"].tolist()] == list(_GOLDEN_EDGE_INDEX)

    def test_edge_diff_matches_the_golden(self):
        _molix_neighbor_list()
        out = NeighborDelegate(cutoff=_CUTOFF).execute({"Z": _CHAIN_Z, "pos": _tensor_pos()})
        for row, expected in zip(out["edge_diff"].tolist(), _GOLDEN_EDGE_DIFF):
            for got, want in zip(row, expected):
                assert got == pytest.approx(want, abs=_POS_ATOL)

    def test_edge_dist_matches_the_golden(self):
        _molix_neighbor_list()
        out = NeighborDelegate(cutoff=_CUTOFF).execute({"Z": _CHAIN_Z, "pos": _tensor_pos()})
        for got, want in zip(out["edge_dist"].tolist(), _GOLDEN_EDGE_DIST):
            assert got == pytest.approx(want, abs=_POS_ATOL)

    def test_edge_count_is_twice_the_pair_count(self):
        _molix_neighbor_list()
        out = NeighborDelegate(cutoff=_CUTOFF).execute({"Z": _CHAIN_Z, "pos": _tensor_pos()})
        assert out["edge_index"].shape == (4, 2)

    def test_task_id_matches_the_golden(self):
        _molix_neighbor_list()
        assert NeighborDelegate(cutoff=_CUTOFF).task_id == _GOLDEN_TASK_ID

    def test_half_pair_mode_drops_the_reverse_edges(self):
        _molix_neighbor_list()
        delegate = NeighborDelegate(cutoff=_CUTOFF, symmetry=False)
        out = delegate.execute({"Z": _CHAIN_Z, "pos": _tensor_pos()})
        assert [tuple(row) for row in out["edge_index"].tolist()] == list(_GOLDEN_HALF_EDGE_INDEX)

    def test_half_pair_mode_has_its_own_task_id(self):
        """Different edge tensors must not share a cache key."""
        _molix_neighbor_list()
        assert NeighborDelegate(cutoff=_CUTOFF, symmetry=False).task_id == _GOLDEN_HALF_TASK_ID


class TestNeighborDelegateIdentity:
    def test_output_equals_the_reference_implementation(self):
        """Identity of output, not a re-derivation of it."""
        neighbor_list = _molix_neighbor_list()
        sample = {"Z": _CHAIN_Z, "pos": _tensor_pos()}
        reference = neighbor_list(cutoff=_CUTOFF).execute(dict(sample))
        delegated = NeighborDelegate(cutoff=_CUTOFF).execute(dict(sample))
        for key in ("edge_index", "edge_diff", "edge_dist"):
            assert delegated[key].tolist() == reference[key].tolist()

    def test_delegate_wraps_the_reference_class(self):
        neighbor_list = _molix_neighbor_list()
        delegate = NeighborDelegate(cutoff=_CUTOFF)
        assert isinstance(delegate.neighbor_list, neighbor_list)
