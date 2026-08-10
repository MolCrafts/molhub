# Migrating

Replace legacy unversioned names with canonical coordinates, `index` terminology with `registry`, and
direct driver calls with `Molhub.fetch`. Cache migration should preserve the
`files/<kind>/<namespace>/<name>@<version>/<role>` layout.

For old manifests, copy platform-published digests instead of converting everything to SHA-256. Add a
size when no digest is published. Declare `format` and `media_type` before enabling Inspector; a file
extension alone is not a contract.

The old split repository idea for Web or TypeScript is retired. Both live in this repository under
`apps/web` and `packages/typescript`.
