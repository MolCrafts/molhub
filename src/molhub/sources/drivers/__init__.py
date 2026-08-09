"""Source drivers and the immutable collection that selects among them."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import entry_points

from molhub.sources.drivers.figshare import FigshareSource
from molhub.sources.drivers.https import HttpsSource
from molhub.sources.drivers.huggingface import HuggingFaceSource
from molhub.sources.drivers.molhub import MolHubSource
from molhub.sources.drivers.zenodo import ZenodoSource
from molhub.sources.errors import UnknownScheme
from molhub.sources.source import Source

__all__ = [
    "Drivers",
    "HttpsSource",
    "ZenodoSource",
    "FigshareSource",
    "HuggingFaceSource",
    "MolHubSource",
]

ENTRY_POINT_GROUP = "molhub.sources"


class Drivers:
    """An immutable set of :class:`Source` drivers, keyed by scheme.

    Every mutating-looking operation returns a new collection, so a caller can
    layer a driver on top of the discovered set without disturbing anything
    else in the process::

        drivers = Drivers.discover().with_driver(MySource())
    """

    def __init__(self, drivers: Iterable[Source] = ()) -> None:
        # Later entries win, so `with_driver` can override a built-in.
        self._by_scheme: dict[str, Source] = {d.scheme.lower(): d for d in drivers}

    @classmethod
    def of(cls, *drivers: Source) -> "Drivers":
        """Build a collection from the given drivers, in order."""
        return cls(drivers)

    @classmethod
    def builtin(cls) -> "Drivers":
        """The drivers molhub ships with, without consulting entry points."""
        return cls(
            (
                HttpsSource(),
                ZenodoSource(),
                FigshareSource(),
                HuggingFaceSource(),
                MolHubSource(),
            )
        )

    @classmethod
    def discover(cls) -> "Drivers":
        """The built-in drivers plus any registered by installed packages.

        Third-party drivers are found through the ``molhub.sources``
        entry-point group and may override a built-in scheme.
        """
        found = list(cls.builtin()._by_scheme.values())
        for entry in entry_points(group=ENTRY_POINT_GROUP):
            found.append(entry.load()())
        return cls(found)

    def with_driver(self, driver: Source) -> "Drivers":
        """Return a **new** collection with *driver* added or overriding.

        The receiver is left unchanged.
        """
        return Drivers([*self._by_scheme.values(), driver])

    def for_scheme(self, scheme: str) -> Source:
        """Return the driver claiming *scheme*.

        Raises:
            UnknownScheme: If no driver claims it. The message lists what is
                available, which is usually enough to spot a typo.
        """
        try:
            return self._by_scheme[scheme.lower()]
        except KeyError:
            available = ", ".join(self.schemes()) or "none"
            raise UnknownScheme(
                f"No source driver for scheme {scheme!r}. Available: {available}."
            ) from None

    def schemes(self) -> tuple[str, ...]:
        """The schemes this collection can handle, in insertion order."""
        return tuple(self._by_scheme)
