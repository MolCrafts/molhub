"""Publication — platform-neutral metadata for something being uploaded.

Deliberately small and typed rather than a free-form mapping: every field here
has a counterpart on all three hosting platforms molhub publishes to. Anything
a platform needs beyond this belongs in that driver's own method, not in a
catch-all bag every layer reaches into.

Each driver documents which fields it cannot express.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Publication"]


@dataclass(frozen=True)
class Publication:
    """What a human should see about a published artifact.

    Attributes:
        title: Human-readable name. The only required field.
        description: Longer prose. Rendered as the abstract on Figshare and as
            the repository card on HuggingFace.
        license: SPDX identifier such as ``"CC0-1.0"``.
        keywords: Free-text tags. The tuple annotation is the contract; the
            constructor also coerces any other iterable to a tuple, so an
            untyped caller passing a list still ends up with a value object
            that is immutable all the way down.
        private: Whether the result should be non-public. Platforms that
            cannot express this reject a ``True`` value rather than silently
            publishing something publicly.
    """

    title: str
    description: str = ""
    license: str | None = None
    keywords: tuple[str, ...] = field(default_factory=tuple)
    private: bool = False

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("Publication.title must not be empty.")
        object.__setattr__(self, "keywords", tuple(self.keywords))
