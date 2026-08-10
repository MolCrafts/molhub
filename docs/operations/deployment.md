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
