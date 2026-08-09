# Incident response

1. Disable public submissions by removing or invalidating the rate-limit/API route at the edge; preserve
   existing D1 records.
2. Rotate exposed GitHub, admin, webhook, and Cloudflare credentials. Audit webhook signature failures.
3. Rebuild the registry from an audited source commit and redeploy the previous known-good Web artifact.
4. Invalidate affected derived preview keys. Do not alter authoritative source manifests to hide a cache
   problem.
5. Record timeframe, affected coordinates/submissions, recovery revision, and follow-up tests.

Logs may contain submission id, coordinate, status, source platform, response class, and bounded error
messages. They must not contain contributor email, token, authorization header, webhook secret, or an
unbounded manifest body.
