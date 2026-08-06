"""Registry drivers and the immutable collection that selects among them."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import entry_points

from molhub.registry.driver import Registry
from molhub.registry.drivers.figshare import FigshareRegistry
from molhub.registry.drivers.https import HttpsRegistry
from molhub.registry.drivers.huggingface import HuggingFaceRegistry
from molhub.registry.drivers.molhub import MolHubRegistry
from molhub.registry.drivers.zenodo import ZenodoRegistry
from molhub.registry.errors import UnknownScheme

__all__ = [
    "Drivers",
    "HttpsRegistry",
    "ZenodoRegistry",
    "FigshareRegistry",
    "HuggingFaceRegistry",
    "MolHubRegistry",
]

ENTRY_POINT_GROUP = "molhub.registries"


class Drivers:
    """An immutable set of :class:`Registry` drivers, keyed by scheme.

    Every mutating-looking operation returns a new collection, so a caller can
    layer a driver on top of the discovered set without disturbing anything
    else in the process::

        drivers = Drivers.discover().with_driver(MyRegistry())
    """

    def __init__(self, drivers: Iterable[Registry] = ()) -> None:
        # Later entries win, so `with_driver` can override a built-in.
        self._by_scheme: dict[str, Registry] = {d.scheme.lower(): d for d in drivers}

    @classmethod
    def of(cls, *drivers: Registry) -> "Drivers":
        """Build a collection from the given drivers, in order."""
        return cls(drivers)

    @classmethod
    def builtin(cls) -> "Drivers":
        """The drivers molhub ships with, without consulting entry points."""
        return cls(
            (
                HttpsRegistry(),
                ZenodoRegistry(),
                FigshareRegistry(),
                HuggingFaceRegistry(),
                MolHubRegistry(),
            )
        )

    @classmethod
    def discover(cls) -> "Drivers":
        """The built-in drivers plus any registered by installed packages.

        Third-party drivers are found through the ``molhub.registries``
        entry-point group and may override a built-in scheme.
        """
        found = list(cls.builtin()._by_scheme.values())
        for entry in entry_points(group=ENTRY_POINT_GROUP):
            found.append(entry.load()())
        return cls(found)

    def with_driver(self, driver: Registry) -> "Drivers":
        """Return a **new** collection with *driver* added or overriding.

        The receiver is left unchanged.
        """
        return Drivers([*self._by_scheme.values(), driver])

    def for_scheme(self, scheme: str) -> Registry:
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
                f"No registry driver for scheme {scheme!r}. Available: {available}."
            ) from None

    def schemes(self) -> tuple[str, ...]:
        """The schemes this collection can handle, in insertion order."""
        return tuple(self._by_scheme)
