# Deployment

Use Node 22 and run all commands from the MolHub repository root.

```bash
npm install
npm run check
npm run dev --workspace @molcrafts/molhub-web
npm run db:migrate:local --workspace @molcrafts/molhub-api
npm run dev --workspace @molcrafts/molhub-api
uv run pytest
```

## Web

Build against a validated canonical registry snapshot, set `PUBLIC_MOLHUB_API_URL` and
`PUBLIC_MOLHUB_REGISTRY_REVISION`, then deploy the immutable `apps/web/dist/client` directory. Smoke
`/molhub/`, Explore, one detail page, Submit, and the 3BPA Inspector route. The footer must show the
registry source revision used for the build.

## Submission API

Create D1 and replace the `wrangler.jsonc` placeholder database id. Store `GITHUB_TOKEN`, `ADMIN_TOKEN`,
and `GITHUB_WEBHOOK_SECRET` with Wrangler secrets. Apply migrations locally first, then remotely; run
Worker tests and `deploy:dry` before deployment. Smoke `/health`, create, and status in staging.

Rollback the Worker with Cloudflare deployment rollback and redeploy the previous immutable Web build.
Rotate a secret by writing the replacement, updating the matching GitHub webhook/client, testing, then
revoking the old credential. Never put secrets in repository variables or `.dev.vars` commits.

## CI and release

| workflow | feature branch (fork or upstream) | dev / master, or a PR into one | upstream only |
|---|---|---|---|
| `lint.yml` | `lint / python` (ruff, ty), `lint / node` (audit, contract, biome, tsc) | same | — |
| `test.yml` | `test / python`, `test / node` (workspaces, parity, Worker dry run, Web build) | + Python 3.13/3.14, macOS, Windows, `test / browser` (Playwright Inspector), `test / package` | — |
| `docs.yml` | `docs / build` (`npm run docs:check`) | same | master: `docs / deploy` (docs site), `docs / web` (MolHub Web; also on molhub-registry's `registry-published`) |
| `deploy.yml` | — | — | master: `deploy / api` (D1 migrations, Worker, `/health`) |
| `nightly.yml` | — | — | weekly: `nightly / molpy` (newest MolPy), `nightly / coverage` |
| `release.yml` | — | — | `v*` tag: `release / build`, `release / publish` (PyPI, npm); `workflow_dispatch` is a dry run anywhere |

A pull request from a branch of the same repository skips the jobs its push
already ran. Every job that needs the registry validates and builds
`molhub-registry` at `dev` (or its branch of the same name) with this
checkout's tools. Each deploy is skipped until its repository variable
(`CLOUDFLARE_DOCS_PROJECT`, `CLOUDFLARE_PAGES_PROJECT`, `MOLHUB_API_URL`) is
set; the Cloudflare credentials are the `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` secrets.

To release, bump the Python and npm versions, merge to master, and push a
`v*` tag; write the GitHub Release from `.github/RELEASE_TEMPLATE.md`.
