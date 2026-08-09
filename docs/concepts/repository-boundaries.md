# Repository boundaries

| Repository or directory | Responsibility |
|---|---|
| `molhub/src` | Python SDK and dataset adapters |
| `molhub/packages/typescript` | Browser/Node SDK and Node CLI |
| `molhub/apps/web` | Product Web and Inspector host |
| `molhub/apps/api` | Submission/review REST API |
| `molhub/spec` | Shared schemas and conformance vectors |
| `molhub-registry/artifacts` | Approved YAML records only |
| Upstream repositories | Scientific payload bytes |

The Web, REST API, Python client, and TypeScript client are one product repository. The registry is a
separate data-only repository so metadata review does not mix with application releases.
