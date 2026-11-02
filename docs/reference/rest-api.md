# REST API

The submission API uses JSON and never proxies artifact bodies.

```http
GET /health
```

```http
POST /v1/submissions
Content-Type: application/json

{"manifest":{"kind":"dataset","namespace":"lab","name":"sample","version":"v1","title":"Sample","license":"CC0-1.0","doi":"10.0000/sample","artifacts":[{"role":"main","filename":"sample.xyz","format":"extxyz","media_type":"chemical/x-xyz","size":4,"locators":["https://example.test/sample.xyz"]}]}}
```

The `201` receipt contains `id`, `coordinate`, `status`, timestamps, review note, and pull request URL.
Use that id with `GET /v1/submissions/:id`. Reviewer queue/actions require a bearer admin token;
rejection also requires a note. Request bodies are capped at 64 KiB and public creation is rate limited.

These exact health/create/status examples are exercised against the local Worker in the API test suite.

Approval records the review decision before creating GitHub resources. If publication fails, the
submission remains `reviewing` with a null `pullRequestUrl`; repeating the approve action resumes
publication. Once linked, repeated approval returns the existing receipt. Rejection is permitted only
while `pending`. Concurrent duplicate submissions return `409` for every request after the first.
Merge notifications are retained even if they arrive before the PR URL is saved.
