# MolHub Web

The MolHub product interface: registry discovery, versioned artifact detail
pages, and direct manifest submission. Product code belongs here; the approved
registry database lives in
[`MolCrafts/molhub-registry`](https://github.com/MolCrafts/molhub-registry).

## Registry boundary

The app consumes one generated `registry.json` snapshot and never writes
approved manifests. Before development, test, typecheck, or production build,
`scripts/sync-registry.ts` uses the canonical registry tooling to build a
sibling database into the ignored `.generated/` directory. CI can provide an
explicit snapshot instead.

Local sibling workflow:

```bash
cd molhub
npm install
npm run dev --workspace @molcrafts/molhub-web
```

CI or a non-sibling checkout supplies the snapshot explicitly:

```bash
MOLHUB_REGISTRY_JSON=/absolute/path/to/registry.json npm run build
```

## Toolchain

- React 19 and TanStack Start
- Rsbuild 2 with static prerendering
- Tailwind CSS 4 over MolHub design tokens
- Rstest through the Rsbuild adapter
- Biome and TypeScript

The static Cloudflare Pages output is `dist/client`. The public router and
asset base is `/molhub/`.

Set `PUBLIC_MOLHUB_API_URL` at build time for direct submission. It defaults to
`http://localhost:8787` in local development.
