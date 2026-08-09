# Using TypeScript

Use the browser export for resolve/search, the Node export for filesystem fetch, and the core export
for contract types and validation.

<!-- test: exec=node -->
```ts
import { Coordinate } from "@molcrafts/molhub/core";

const coordinate = Coordinate.parse("qm9@v2");
if (coordinate.canonical !== "dataset:molcrafts/qm9@v2") throw new Error("bad coordinate");
```

<!-- test: typecheck -->
```ts
import { Molhub } from "@molcrafts/molhub";

const hub = new Molhub({ registry: "/registry.json" });
const matches = await hub.search({ query: "trajectory", kind: "dataset" });
console.log(matches.map((entry) => entry.coordinate));
```

Node additionally accepts a local snapshot path and shares the Python cache layout.
