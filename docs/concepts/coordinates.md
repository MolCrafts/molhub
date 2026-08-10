# Coordinates

A coordinate has the canonical form `kind:namespace/name@version`. The version is mandatory and
`latest` is never resolved implicitly.

<!-- test: exec -->
```python
from molhub import Coordinate

coordinate = Coordinate.parse("qm9@v2")
assert coordinate.canonical == "dataset:molcrafts/qm9@v2"
assert coordinate.cache_path() == "dataset/molcrafts/qm9@v2"
```

Coordinates belong to MolHub. Locators belong to upstream platforms and may be replaced or reordered
without changing user code.
