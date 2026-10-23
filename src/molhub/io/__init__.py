"""On-disk engines and the mrec collection laid over them.

:class:`Lmdb` and :class:`Hdf5` open a file. :class:`MrecRecords` reads an
mrec collection from either. :class:`AseRows` reads ASE row bytes from an
:class:`Lmdb`. None of them is a dataset.
"""

from molhub.io.ase import RESERVED_KEYS, AseRows, decode_row, encode_row
from molhub.io.hdf5 import Hdf5
from molhub.io.lmdb import Lmdb
from molhub.io.mrec import MrecRecords, MrecWriter

__all__ = [
    "AseRows",
    "Hdf5",
    "Lmdb",
    "MrecRecords",
    "MrecWriter",
    "RESERVED_KEYS",
    "decode_row",
    "encode_row",
]
