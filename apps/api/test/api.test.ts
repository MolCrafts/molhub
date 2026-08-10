import { createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

import worker from "../src/index.js";

describe("submission API", () => {
  it("keeps the documented health, create, and status examples executable", async () => {
    const health = await call("/health");
    expect(health.status).toBe(200);
    expect(await health.json()).toEqual({ status: "ok" });

    const name = `docs-${crypto.randomUUID().slice(0, 8)}`;
    const created = await call("/v1/submissions", {
      method: "POST",
      headers: { "content-type": "application/json", "user-agent": name },
      body: JSON.stringify({ manifest: manifest(name) }),
    });
    expect(created.status).toBe(201);
    const receipt = await created.json<{ id: string; coordinate: string }>();
    expect(receipt.coordinate).toBe(`dataset:lab/${name}@v1`);
    const status = await call(`/v1/submissions/${receipt.id}`);
    expect(status.status).toBe(200);
  });

  it("creates a submission and exposes its review status without GitHub", async () => {
    const name = `sample-${crypto.randomUUID().slice(0, 8)}`;
    const created = await call("/v1/submissions", {
      method: "POST",
      headers: { "content-type": "application/json", origin: env.WEB_ORIGIN },
      body: JSON.stringify({
        manifest: manifest(name),
        contributor: { name: "Ada", email: "ada@example.org" },
      }),
    });
    expect(created.status).toBe(201);
    expect(created.headers.get("access-control-allow-origin")).toBe(env.WEB_ORIGIN);
    const submission = await created.json<{ id: string; coordinate: string; status: string }>();
    expect(submission.coordinate).toBe(`dataset:lab/${name}@v1`);
    expect(submission.status).toBe("pending");

    const status = await call(`/v1/submissions/${submission.id}`);
    expect(status.status).toBe(200);
    expect(await status.json()).toMatchObject({ id: submission.id, status: "pending" });
  });

  it("rejects invalid manifests with shared contract issues", async () => {
    const response = await call("/v1/submissions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ manifest: { schema_version: 1 } }),
    });
    expect(response.status).toBe(422);
    expect(await response.json()).toMatchObject({ error: "invalid_manifest" });
  });

  it("lets an authenticated reviewer reject with an actionable note", async () => {
    const name = `reject-${crypto.randomUUID().slice(0, 8)}`;
    const created = await call("/v1/submissions", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ manifest: manifest(name) }),
    });
    const submission = await created.json<{ id: string }>();
    const reviewed = await call(`/v1/submissions/${submission.id}/review`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.ADMIN_TOKEN}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ decision: "reject", note: "Use a version-specific DOI." }),
    });
    expect(reviewed.status).toBe(200);
    expect(await reviewed.json()).toMatchObject({
      status: "rejected",
      reviewNote: "Use a version-specific DOI.",
    });
  });

  it("gives an authenticated reviewer a work queue without contributor email", async () => {
    const name = `queue-${crypto.randomUUID().slice(0, 8)}`;
    const created = await call("/v1/submissions", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "user-agent": name,
      },
      body: JSON.stringify({
        manifest: manifest(name),
        contributor: { name: "Ada", email: "private@example.org" },
      }),
    });
    expect(created.status).toBe(201);
    const queue = await call("/v1/review/submissions?status=pending", {
      headers: { authorization: `Bearer ${env.ADMIN_TOKEN}` },
    });
    expect(queue.status).toBe(200);
    const body = await queue.text();
    expect(body).toContain(`dataset:lab/${name}@v1`);
    expect(body).toContain('"name":"Ada"');
    expect(body).not.toContain("private@example.org");
  });

  it("rate limits repeated anonymous submissions before D1 work", async () => {
    const actor = `rate-${crypto.randomUUID()}`;
    const statuses: number[] = [];
    for (let index = 0; index < 6; index += 1) {
      const response = await call("/v1/submissions", {
        method: "POST",
        headers: { "content-type": "application/json", "user-agent": actor },
        body: JSON.stringify({ manifest: manifest(`${actor.slice(0, 16)}-${index}`) }),
      });
      statuses.push(response.status);
    }
    expect(statuses.slice(0, 5)).toEqual([201, 201, 201, 201, 201]);
    expect(statuses[5]).toBe(429);
  });
});

async function call(path: string, init?: RequestInit): Promise<Response> {
  const context = createExecutionContext();
  const response = await worker.fetch(
    new Request(`https://api.molcrafts.test${path}`, init),
    env,
    context,
  );
  await waitOnExecutionContext(context);
  return response;
}

function manifest(name: string): object {
  return {
    schema_version: 1,
    kind: "dataset",
    namespace: "lab",
    name,
    version: "v1",
    title: "Sample",
    license: "CC0-1.0",
    doi: "10.0000/sample",
    artifacts: [
      {
        role: "main",
        filename: "sample.xyz",
        format: "extxyz",
        media_type: "chemical/x-xyz",
        size: 4,
        locators: ["https://example.test/sample.xyz"],
      },
    ],
  };
}
