"""MolHub — molecular dataset hub.

Provides:

* ``molhub.dataset`` — map-style / iterable-style dataset protocols
  plus built-in dataset sources (QM9, revMD17, 3BPA).
* ``molhub.uploader`` — upload utilities for HuggingFace Hub and Figshare.
"""

from molhub._version import __version__

__all__ = ["__version__"]
