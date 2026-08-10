import { describe, expect, it, vi } from "vitest";

import { SubmissionApi } from "../src/http.js";
import type { SubmissionService } from "../src/service.js";

describe("operational logging", () => {
  it("does not log contributor data, credentials, or an exception message", async () => {
    const sensitive = "private@example.org Bearer top-secret manifest-body";
    const service = {
      create: async () => {
        throw new Error(sensitive);
      },
    } as unknown as SubmissionService;
    const log = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const api = new SubmissionApi(service, "https://app.molcrafts.test", {
      adminToken: null,
      webhookSecret: null,
      rateLimiter: { limit: async () => ({ success: true }) } as RateLimit,
    });

    const response = await api.handle(
      new Request("https://api.molcrafts.test/v1/submissions", {
        method: "POST",
        headers: { "content-type": "application/json", authorization: "Bearer top-secret" },
        body: JSON.stringify({
          manifest: { schema_version: 1 },
          contributor: { email: "private@example.org" },
        }),
      }),
    );

    expect(response.status).toBe(500);
    expect(await response.text()).not.toContain(sensitive);
    const logged = log.mock.calls.flat().join(" ");
    expect(logged).toContain('"error":"Error"');
    expect(logged).not.toContain("private@example.org");
    expect(logged).not.toContain("top-secret");
    expect(logged).not.toContain("manifest-body");
    log.mockRestore();
  });
});
