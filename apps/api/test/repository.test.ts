import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import type { Submission } from "../src/domain.js";
import { D1SubmissionRepository } from "../src/repository.js";

// Repository-only tests: the local D1 binding executes SQL; no service, HTTP or GitHub graph.
describe("D1SubmissionRepository", () => {
  it("atomically allows one active coordinate and permits resubmission after rejection", async () => {
    const repository = new D1SubmissionRepository(env.DB);
    const first = submission();
    const second = { ...first, id: crypto.randomUUID() };
    const inserted = await Promise.all([repository.insert(first), repository.insert(second)]);
    expect(inserted.filter(Boolean)).toHaveLength(1);
    const active = inserted[0] ? first : second;
    expect(
      await repository.transition(active.id, "pending", "rejected", { note: "revise" }),
    ).toMatchObject({ status: "rejected" });
    expect(await repository.insert({ ...first, id: crypto.randomUUID() })).toBe(true);
  });

  it("allows only one competing decision to change a pending record", async () => {
    const repository = new D1SubmissionRepository(env.DB);
    const record = submission();
    await repository.insert(record);
    const results = await Promise.all([
      repository.transition(record.id, "pending", "reviewing", { note: "approve" }),
      repository.transition(record.id, "pending", "rejected", { note: "reject" }),
    ]);
    expect(results.filter((result) => result !== null)).toHaveLength(1);
    expect((await repository.get(record.id))?.status).toBe(results.find(Boolean)?.status);
  });

  it.each(["before", "after"])(
    "preserves merge notifications arriving %s PR persistence",
    async (when) => {
      const repository = new D1SubmissionRepository(env.DB);
      const record = submission();
      const url = `https://github.test/pull/${record.id}`;
      await repository.insert(record);
      await repository.transition(record.id, "pending", "reviewing", { note: "approved" });
      if (when === "before") await repository.markAcceptedByPullRequest(url);
      await repository.transition(record.id, "reviewing", "reviewing", { pullRequestUrl: url });
      if (when === "after") await repository.markAcceptedByPullRequest(url);
      await repository.markAcceptedByPullRequest(url);
      expect(await repository.get(record.id)).toMatchObject({
        status: "accepted",
        pullRequestUrl: url,
        reviewNote: "approved",
      });
      expect(
        await repository.transition(record.id, "reviewing", "reviewing", { pullRequestUrl: url }),
      ).toBeNull();
    },
  );
});

function submission(): Submission {
  const id = crypto.randomUUID();
  return {
    id,
    coordinate: `dataset:lab/test-${id}@v1`,
    manifest: {
      kind: "dataset",
      namespace: "lab",
      name: `test-${id}`,
      version: "v1",
      title: "Test",
      artifacts: [
        { role: "main", filename: "test", size: 4, locators: ["https://example.test/test"] },
      ],
    },
    manifestYaml: "test",
    status: "pending",
    contributor: {},
    reviewNote: null,
    pullRequestUrl: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}
