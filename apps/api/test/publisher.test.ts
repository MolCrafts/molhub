import { describe, expect, it } from "vitest";

import { GitHubRegistryPublisher } from "../src/publisher.js";

describe("GitHubRegistryPublisher", () => {
  it("creates an isolated branch, manifest commit, and pull request", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const replies = [
      Response.json({ object: { sha: "base-sha" } }),
      Response.json({ message: "Not Found" }, { status: 404 }),
      Response.json({ ref: "refs/heads/molhub/submission-abc" }, { status: 201 }),
      Response.json({ content: { path: "manifest.yaml" } }, { status: 201 }),
      Response.json(
        { html_url: "https://github.com/MolCrafts/molhub-registry/pull/12" },
        { status: 201 },
      ),
    ];
    const publisher = new GitHubRegistryPublisher({
      token: "secret-token",
      repository: "MolCrafts/molhub-registry",
      baseBranch: "main",
      fetch: async (input, init = {}) => {
        requests.push({ url: String(input), init });
        const reply = replies.shift();
        if (!reply) throw new Error("Unexpected GitHub request.");
        return reply;
      },
    });

    const result = await publisher.publish({
      submissionId: "abc",
      coordinate: "dataset:acme/example@v1",
      manifestYaml: "schema_version: 1\n",
    });

    expect(result.pullRequestUrl).toBe("https://github.com/MolCrafts/molhub-registry/pull/12");
    expect(requests.map((request) => new URL(request.url).pathname)).toEqual([
      "/repos/MolCrafts/molhub-registry/git/ref/heads/main",
      "/repos/MolCrafts/molhub-registry/contents/artifacts/dataset/acme/example/v1.yaml",
      "/repos/MolCrafts/molhub-registry/git/refs",
      "/repos/MolCrafts/molhub-registry/contents/artifacts/dataset/acme/example/v1.yaml",
      "/repos/MolCrafts/molhub-registry/pulls",
    ]);
    expect(
      requests.every(
        (request) =>
          new Headers(request.init.headers).get("authorization") === "Bearer secret-token",
      ),
    ).toBe(true);

    const commit = JSON.parse(String(requests[3]?.init.body));
    expect(commit.branch).toBe("molhub/submission-abc");
    expect(atob(commit.content)).toBe("schema_version: 1\n");
  });
});
