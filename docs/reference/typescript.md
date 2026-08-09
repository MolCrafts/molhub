# TypeScript reference

The public exports are intentionally split by runtime:

| Export | Environment | Surface |
|---|---|---|
| `@molcrafts/molhub` | Browser | `Molhub.resolve`, `Molhub.search` |
| `@molcrafts/molhub/node` | Node | resolve, search, fetch, filesystem cache |
| `@molcrafts/molhub/core` | Any | coordinates, registry, types, manifest validator |

The Node CLI is installed as `molhub-js` and mirrors the human-visible Python `search`, `info`, and
`fetch --into` behavior. Generated declaration files are audited in the npm tarball release gate.

The [generated TypeScript API](../../typescript-api/) lists every exported class, interface,
function, and type from the browser, Node, and runtime-neutral entry points. It is generated from
the same source files used to build the npm package.
