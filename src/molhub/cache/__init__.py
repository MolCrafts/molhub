"""Cached per-row count vectors.

A packing budget needs one integer per row. Containers that already hold that
number answer from it; containers that would have to decode every record cache
the vector instead, keyed by a fingerprint of the files it was measured from.

See :class:`~molhub.cache.counts.CountSidecar` for why the key is a
fingerprint rather than a description of the dataset.
"""

from molhub.cache.counts import CountSidecar

__all__ = ["CountSidecar"]
