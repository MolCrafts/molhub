# MolHub submission API

A Cloudflare Worker backed by D1. It accepts manifests from the MolHub website,
stores review state, and turns approved submissions into pull requests against
the data-only `MolCrafts/molhub-registry` repository.

## Local development

From the `molhub` repository root:

```bash
npm install
cp apps/api/.dev.vars.example apps/api/.dev.vars
npm run db:migrate:local --workspace @molcrafts/molhub-api
npm run dev --workspace @molcrafts/molhub-api
```

The Worker listens on `http://localhost:8787`. In another terminal run the web
app with `npm run dev --workspace @molcrafts/molhub-web`, then open
`http://localhost:4173/molhub/`.

## API

- `POST /v1/submissions` — public manifest submission
- `GET /v1/submissions/:id` — public submission status
- `GET /v1/review/submissions` — authenticated reviewer queue
- `POST /v1/submissions/:id/review` — authenticated approve/reject action
- `POST /v1/github/webhook` — signed pull-request merge webhook
- `GET /health` — health check

Review requests use `Authorization: Bearer <ADMIN_TOKEN>`. Approval creates a
branch, manifest file, and pull request. Rejection requires a note. A signed
GitHub `pull_request` webhook marks merged submissions as accepted.

Public submissions are limited to five requests per actor fingerprint per
minute by the `SUBMISSION_RATE_LIMITER` Cloudflare binding. The fingerprint is
SHA-256 hashed in the Worker and is never stored with the submission.

## Cloudflare setup

Create the D1 database once, replace the placeholder `database_id` in
`wrangler.jsonc`, then configure secrets and migrate before deploying:

```bash
npx wrangler d1 create molhub-submissions
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put ADMIN_TOKEN
npx wrangler secret put GITHUB_WEBHOOK_SECRET
npm run db:migrate:remote --workspace @molcrafts/molhub-api
npm run deploy --workspace @molcrafts/molhub-api
```

`WEB_ORIGIN` is the deployed `https://app.molcrafts.org` origin; the dev script
overrides it with `http://localhost:4173`. Configure GitHub to send
`pull_request` events to `/v1/github/webhook` using the same webhook secret.
