"""Locator — where one artifact lives on one remote source.

A locator is upstream-owned and may change; the molhub coordinate that points
at it does not. Keeping the two apart is what lets a mirror be added or a
gated repository be swapped without touching user code.
"""

from __future__ import annotations

from dataclasses import dataclass

from molhub.sources.errors import InvalidLocator

__all__ = ["Locator"]

_SEPARATOR = "://"


@dataclass(frozen=True)
class Locator:
    """A ``scheme://path`` reference to bytes on some remote.

    The *scheme* selects the driver (``zenodo``, ``hf``, ``figshare``, …);
    the *path* is opaque to molhub and interpreted by that driver alone.

    Attributes:
        scheme: Lower-cased driver selector.
        path: Driver-specific remainder, never empty.
    """

    scheme: str
    path: str

    @classmethod
    def parse(cls, text: str) -> "Locator":
        """Parse a locator string.

        Args:
            text: A ``scheme://path`` string.

        Returns:
            The parsed :class:`Locator`.

        Raises:
            InvalidLocator: If *text* lacks a scheme, lacks a path, or does not
                contain the ``://`` separator.
        """
        candidate = text.strip()
        scheme, separator, path = candidate.partition(_SEPARATOR)
        if not separator or not scheme or not path:
            raise InvalidLocator(
                f"Malformed locator {text!r}; expected 'scheme://path' with both parts non-empty."
            )
        return cls(scheme=scheme.lower(), path=path)

    @classmethod
    def coerce(cls, value: "str | Locator") -> "Locator":
        """Return *value* as a :class:`Locator`, parsing it when it is a string.

        The check is against :class:`Locator`, not ``cls``: narrowing on a
        subclass would send an already-parsed base ``Locator`` down the string
        branch and fail on ``text.strip()``.
        """
        return value if isinstance(value, Locator) else cls.parse(value)

    def __str__(self) -> str:
        return f"{self.scheme}{_SEPARATOR}{self.path}"
