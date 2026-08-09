# Finding and fetching

Resolution and search are offline when using the bundled Python registry.

<!-- test: exec -->
```python
from molhub import Molhub

hub = Molhub()
entry = hub.resolve("polymer-tg@1")
assert entry.coordinate.canonical == "dataset:molcrafts/polymer-tg@1"
assert hub.search(query="polymer")[0].coordinate.name == "polymer-tg"
```

Fetching contacts the ordered locators only on a cold cache:

```bash
molhub search polymer
molhub info dataset:molcrafts/polymer-tg@1
molhub fetch polymer-tg@1 --into ./data
```

In Python, call `hub.fetch(coordinate, roles=["main"])`. In Node, pass an explicit registry snapshot
to `Molhub` and call its asynchronous `fetch` method.
