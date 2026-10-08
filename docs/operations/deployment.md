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

Each workflow's first job, `<file> / context`, runs
[`MolCrafts/molcrafts-ci/actions/ci-context`](https://github.com/MolCrafts/molcrafts-ci/tree/master/actions/ci-context),
and every other job gates on its outputs (tier, upstream, pull request
dedup). The fast tier runs on a feature-branch push to
MolCrafts; the full tier on every push to a fork (proven before its pull
request), on `dev`, `master` and `main` on MolCrafts, on pull requests, tags
and dispatches.

| workflow | fast tier | full tier | upstream only |
|---|---|---|---|
| `lint.yml` | `lint / python` (partners, lock, ruff, ty), `lint / node` (audit, contract, biome, tsc), `lint / workflows` (`actions/check-workflows`) | same | — |
| `test.yml` | `test / context`, `test / python (ubuntu-latest, 3.12)`, `test / node` (workspaces, parity, Worker dry run, Web build) | + Python 3.13/3.14, macOS, Windows, `test / package` | — |
| `docs.yml` | `docs / build` (`npm run docs:check`) | same | master: `docs / deploy` (docs site), `docs / web` (MolHub Web; also on molhub-registry's `registry-published`) |
| `deploy.yml` | — | — | master: `deploy / api` (D1 migrations, Worker, `/health`) |
| `nightly.yml` | — | — | weekly: `nightly / coverage` |
| `release.yml` | — | — | `v*` tag: `release / guard`, lint + test (full), `release / build`, `release / pypi`, `release / npm`; `workflow_dispatch` is a dry run anywhere |

A pull request inside a fork is skipped: its push already ran the full tier.
CI builds molhub against its partners, never against published releases or a
developer's own sibling checkouts: `.github/partners.env` names them (molpy and
molrs on `dev`), and `scripts/partners.py` resolves each to that branch, or to
the partner's branch named like the one being built. The partners are checked
out as siblings (`../molpy`, `../molrs`), the layout the `[tool.uv.sources]`
path dependencies expect, and molrs is built from source. The git hooks run ty
and the unit suite in the same layout (`scripts/partners.py run`), so a local
gate and CI judge the same partner commits. `uv.lock` is committed and
universal; relock in that layout with
`python3 scripts/partners.py run -- bash -c 'uv lock && cp uv.lock "$PARTNERS_SOURCE"/'`.
The shared setup actions come from `MolCrafts/molcrafts-ci/actions/*@master`.
Every job that needs the registry validates and builds
`molhub-registry` at `dev` (or its branch of the same name) with this
checkout's tools. Each deploy is skipped until its repository variable
(`CLOUDFLARE_DOCS_PROJECT`, `CLOUDFLARE_PAGES_PROJECT`, `MOLHUB_API_URL`) is
set; the Cloudflare credentials are the `CLOUDFLARE_API_TOKEN` and
`CLOUDFLARE_ACCOUNT_ID` secrets.

To release, bump the Python and npm versions, merge to master, and push a
`v*` tag; write the GitHub Release from `.github/RELEASE_TEMPLATE.md`.
