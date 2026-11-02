import { describe, expect, it } from "vitest";

import { GitHubRegistryPublisher } from "../src/publisher.js";

const REQUEST = {
  submissionId: "abc",
  coordinate: "dataset:acme/example@v1",
  manifestYaml: "kind: dataset\n",
};
const PR_URL = "https://github.com/MolCrafts/molhub-registry/pull/12";

describe("GitHubRegistryPublisher", () => {
  it("publishes once and reuses the same PR across retries and concurrent calls", async () => {
    const github = new FakeGitHub();
    const publisher = new GitHubRegistryPublisher({
      token: "secret-token",
      repository: "MolCrafts/molhub-registry",
      baseBranch: "master",
      fetch: github.fetch,
    });
    const results = await Promise.all([publisher.publish(REQUEST), publisher.publish(REQUEST)]);
    expect(results.map((result) => result.pullRequestUrl)).toEqual([PR_URL, PR_URL]);
    expect((await publisher.publish(REQUEST)).pullRequestUrl).toBe(PR_URL);
    expect(github.branches).toBe(1);
    expect(github.commits).toBe(1);
    expect(github.pulls).toBe(1);
    expect(atob(github.content ?? "")).toBe(REQUEST.manifestYaml);
    expect(github.authorizations.every((value) => value === "Bearer secret-token")).toBe(true);
  });

  it.each(["branch", "content", "pull"])("recovers a lost %s response", async (stage) => {
    const github = new FakeGitHub();
    github.loseResponse = stage;
    const publisher = new GitHubRegistryPublisher({
      token: "token",
      repository: "MolCrafts/molhub-registry",
      baseBranch: "master",
      fetch: github.fetch,
    });
    expect((await publisher.publish(REQUEST)).pullRequestUrl).toBe(PR_URL);
    expect(github.pulls).toBe(1);
  });

  it.each(["content", "pull"])("resumes an interrupted %s operation", async (stage) => {
    const github = new FakeGitHub();
    github.failBefore = stage;
    const publisher = new GitHubRegistryPublisher({
      token: "token",
      repository: "MolCrafts/molhub-registry",
      baseBranch: "master",
      fetch: github.fetch,
    });
    await expect(publisher.publish(REQUEST)).rejects.toThrow("unavailable");
    github.failBefore = null;
    expect((await publisher.publish(REQUEST)).pullRequestUrl).toBe(PR_URL);
    expect(github.branches).toBe(1);
    expect(github.commits).toBe(1);
    expect(github.pulls).toBe(1);
  });

  it("recovers an already merged PR even after its branch was deleted", async () => {
    const github = new FakeGitHub();
    github.pulls = 1;
    github.merged = true;
    const publisher = new GitHubRegistryPublisher({
      token: "token",
      repository: "MolCrafts/molhub-registry",
      baseBranch: "master",
      fetch: github.fetch,
    });
    expect(await publisher.publish(REQUEST)).toEqual({ pullRequestUrl: PR_URL, merged: true });
    expect(github.branches).toBe(0);
  });

  it("does not overwrite a conflicting manifest on an existing branch", async () => {
    const github = new FakeGitHub();
    github.branches = 1;
    github.content = btoa("other bytes");
    const publisher = new GitHubRegistryPublisher({
      token: "token",
      repository: "MolCrafts/molhub-registry",
      baseBranch: "master",
      fetch: github.fetch,
    });
    await expect(publisher.publish(REQUEST)).rejects.toThrow("different manifest");
    expect(github.commits).toBe(0);
    expect(github.pulls).toBe(0);
  });
});

/** An injected GitHub boundary; no network or sibling module implementations. */
class FakeGitHub {
  branches = 0;
  commits = 0;
  pulls = 0;
  merged = false;
  content: string | null = null;
  loseResponse: string | null = null;
  failBefore: string | null = null;
  readonly authorizations: Array<string | null> = [];

  readonly fetch: typeof globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    const method = init.method ?? "GET";
    this.authorizations.push(new Headers(init.headers).get("authorization"));
    if (method === "GET") {
      if (url.pathname.endsWith("/pulls")) {
        if (
          url.searchParams.get("head") !== "MolCrafts:molhub/submission-abc" ||
          url.searchParams.get("base") !== "master" ||
          url.searchParams.get("state") !== "all"
        ) {
          throw new Error("Incorrect PR identity query");
        }
        return Response.json(
          this.pulls
            ? [
                {
                  html_url: PR_URL,
                  state: this.merged ? "closed" : "open",
                  merged_at: this.merged ? "2026-10-23T00:00:00Z" : null,
                },
              ]
            : [],
        );
      }
      if (url.pathname.includes("/git/ref/heads/")) {
        return url.pathname.endsWith("/master") || this.branches
          ? Response.json({ object: { sha: "base-sha" } })
          : new Response(null, { status: 404 });
      }
      if (url.pathname.includes("/contents/")) {
        return url.searchParams.get("ref") !== "master" && this.content
          ? Response.json({ content: `${this.content}\n` })
          : new Response(null, { status: 404 });
      }
    }
    const stage = url.pathname.endsWith("/git/refs")
      ? "branch"
      : url.pathname.includes("/contents/")
        ? "content"
        : "pull";
    if (this.failBefore === stage) throw new Error("GitHub unavailable");
    let response: Response;
    if (stage === "branch") {
      if (this.branches) return new Response(null, { status: 422 });
      this.branches++;
      response = Response.json({ ref: "refs/heads/molhub/submission-abc" });
    } else if (stage === "content") {
      if (this.content) return new Response(null, { status: 422 });
      const body = JSON.parse(String(init.body));
      expect(body.branch).toBe("molhub/submission-abc");
      this.content = body.content;
      this.commits++;
      response = Response.json({ content: { path: "manifest.yaml" } });
    } else {
      if (this.pulls) return new Response(null, { status: 422 });
      this.pulls++;
      response = Response.json({ html_url: PR_URL });
    }
    if (this.loseResponse === stage) {
      this.loseResponse = null;
      throw new Error("response lost");
    }
    return response;
  };
}
