"""CSV dataset: download + parse CSV files into :class:`Frame` objects.

Zero extra dependencies — uses stdlib ``csv`` and ``urllib``.

Each row of the CSV becomes one :class:`Frame` with all column values
stored in ``frame.metadata``.  Numeric columns are auto-detected.

Usage::

    from molhub.dataset import CSVDataset

    ds = CSVDataset("https://zenodo.org/records/14980914/files/LAMALAB_CURATED_Tg_structured.csv")
    print(len(ds))       # number of rows
    frame = ds[0]        # first row as a Frame
    print(frame.metadata["labels.Exp_Tg(K)"])   # access a column

    # Also works with local files:
    ds = CSVDataset("/path/to/data.csv")
"""

from __future__ import annotations

import csv
import os
import urllib.request
from pathlib import Path
from typing import Any

from molpy.core.frame import Frame

# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def _infer_value(raw: str) -> str | int | float:
    """Auto-detect numeric type; fall back to string."""
    s = raw.strip()
    if not s:
        return s
    # try int first, then float, then keep as str
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_csv(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Parse a CSV file into headers + list of row dicts.

    Returns:
        (headers, rows) where each row is ``{header: value}``.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return [], []

        headers = [h.strip() for h in headers]
        rows: list[dict[str, Any]] = []
        for raw_row in reader:
            if not raw_row:
                continue
            row = {headers[i]: _infer_value(raw_row[i]) for i in range(len(headers))}
            rows.append(row)

    return headers, rows


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------


def _filename_from_url(url: str) -> str:
    """Extract a plausible filename from a URL."""
    path = url.split("?")[0]
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return name or "data.csv"


def _download(url: str, dest: Path) -> None:
    """Download *url* to *dest* with a User-Agent header."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        dest.write_bytes(r.read())


# ---------------------------------------------------------------------------
# CSVDataset
# ---------------------------------------------------------------------------


class CSVDataset:
    """Map-style dataset backed by a CSV file (local or remote).

    Args:
        path_or_url: Local file path or remote URL to a CSV file.
        cache_dir: Directory for downloaded CSVs.  Defaults to
            ``$MOLHUB_CACHE_DIR``, then ``~/.cache/molhub``.
        download: If True (default), download the file when *path_or_url*
            is a remote URL and the file is not already cached.
    """

    def __init__(
        self,
        path_or_url: str,
        *,
        cache_dir: str | Path | None = None,
        download: bool = True,
    ) -> None:
        self._url: str | None = None
        self._path: Path

        if path_or_url.startswith(("http://", "https://")):
            self._url = path_or_url
            self._path = self._resolve_cache_path(cache_dir)
            if download and not self._path.exists():
                self._ensure_downloaded()
            if not self._path.exists():
                raise FileNotFoundError(
                    f"CSV not found at {self._path}. Set download=True or pre-download the file."
                )
        else:
            self._path = Path(path_or_url)
            if not self._path.exists():
                raise FileNotFoundError(f"CSV file not found: {self._path}")

        self._headers, self._rows = _parse_csv(self._path)

    # -- cache path ----------------------------------------------------------

    def _resolve_cache_path(self, cache_dir: str | Path | None) -> Path:
        if cache_dir is not None:
            root = Path(cache_dir)
        elif "MOLHUB_CACHE_DIR" in os.environ:
            root = Path(os.environ["MOLHUB_CACHE_DIR"])
        else:
            root = Path.home() / ".cache" / "molhub"
        root.mkdir(parents=True, exist_ok=True)
        return root / _filename_from_url(self._url)  # type: ignore[arg-type]

    # -- download ------------------------------------------------------------

    def _ensure_downloaded(self) -> None:
        assert self._url is not None
        _download(self._url, self._path)

    @classmethod
    def download(cls, url: str, cache_dir: str | Path | None = None) -> Path:
        """Download a CSV from *url* without parsing it."""
        dest = cls._resolve_cache_path_static(url, cache_dir)
        if not dest.exists():
            _download(url, dest)
        return dest

    @staticmethod
    def _resolve_cache_path_static(url: str, cache_dir: str | Path | None = None) -> Path:
        if cache_dir is not None:
            root = Path(cache_dir)
        elif "MOLHUB_CACHE_DIR" in os.environ:
            root = Path(os.environ["MOLHUB_CACHE_DIR"])
        else:
            root = Path.home() / ".cache" / "molhub"
        root.mkdir(parents=True, exist_ok=True)
        return root / _filename_from_url(url)

    # -- MapDataset protocol -------------------------------------------------

    @property
    def source_id(self) -> str:
        return f"csv:{self._path.name}:n={len(self._rows)}"

    def __len__(self) -> int:
        return len(self._rows)

    def __getitem__(self, idx: int) -> Frame:
        row = self._rows[idx]
        frame = Frame()
        frame.metadata.update(row)
        return frame

    # -- introspection -------------------------------------------------------

    @property
    def headers(self) -> list[str]:
        """Column names from the CSV header row."""
        return list(self._headers)

    @property
    def path(self) -> Path:
        """Path to the local CSV file."""
        return self._path
