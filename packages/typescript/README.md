# @molcrafts/molhub

TypeScript client for the MolHub registry.

```bash
npm install @molcrafts/molhub
```

Browser code can resolve and search a registry:

```ts
import { Molhub } from "@molcrafts/molhub";

const hub = new Molhub({ registry: "/registry.json" });
const entries = await hub.search({ query: "qm9" });
```

Node code additionally fetches artifacts into the cache shared with the Python
client:

```ts
import { Molhub } from "@molcrafts/molhub/node";

const hub = new Molhub({ registry: "./registry.json" });
const files = await hub.fetch("dataset:molcrafts/qm9@v2");
```

`@molcrafts/molhub/core` exports coordinates, manifests, registry types, and
the shared validator without browser or filesystem I/O.
