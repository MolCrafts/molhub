import type { ManifestDocument } from "@molcrafts/molhub/core";
import { describe, expect, it } from "@rstest/core";

import { SubmissionApiError, SubmissionClient } from "./submissions";

const manifest: ManifestDocument = {
  schema_version: 1,
  kind: "dataset",
  namespace: "acme",
  name: "example",
  version: "v1",
  title: "Example",
  doi: "10.0000/example",
  artifacts: [
    {
      role: "main",
      filename: "example.xyz",
      locators: ["zenodo://1/example.xyz"],
      size: 3,
    },
  ],
};

const receipt = {
  id: "0198-submit",
  coordinate: "dataset:acme/example@v1",
  status: "pending" as const,
  reviewNote: null,
  pullRequestUrl: null,
  createdAt: "2026-08-09T00:00:00.000Z",
  updatedAt: "2026-08-09T00:00:00.000Z",
};

describe("SubmissionClient", () => {
  it("submits a manifest without sending the user to GitHub", async () => {
    let request: Request | undefined;
    const client = new SubmissionClient("https://api.example.test", async (input, init) => {
      request = new Request(input, init);
      return Response.json(receipt, { status: 201 });
    });

    await expect(client.submit(manifest, { email: "chemist@example.test" })).resolves.toEqual(
      receipt,
    );
    expect(request?.url).toBe("https://api.example.test/v1/submissions");
    expect(request?.method).toBe("POST");
    expect(await request?.json()).toEqual({
      manifest,
      contributor: { email: "chemist@example.test" },
    });
  });

  it("reads submission status", async () => {
    const client = new SubmissionClient("https://api.example.test/", async (input) => {
      expect(String(input)).toBe("https://api.example.test/v1/submissions/0198-submit");
      return Response.json({ ...receipt, status: "reviewing" });
    });
    await expect(client.get("0198-submit")).resolves.toMatchObject({ status: "reviewing" });
  });

  it("preserves shared validation issues returned by the API", async () => {
    const issues = [{ code: "missing_doi", path: "/doi", message: "Add a DOI." }] as const;
    const client = new SubmissionClient("https://api.example.test", async () =>
      Response.json({ error: "invalid_manifest", issues }, { status: 422 }),
    );
    const error = await client
      .submit({ ...manifest, doi: undefined })
      .catch((reason: unknown) => reason);
    expect(error).toBeInstanceOf(SubmissionApiError);
    expect((error as SubmissionApiError).issues).toEqual(issues);
  });

  it("loads and reviews the protected queue with a bearer token", async () => {
    const requests: Request[] = [];
    const queued = { ...receipt, manifest, manifestYaml: "schema_version: 1\n", contributor: {} };
    const client = new SubmissionClient("https://api.example.test", async (input, init) => {
      const request = new Request(input, init);
      requests.push(request);
      return request.method === "GET"
        ? Response.json([queued])
        : Response.json({ ...receipt, status: "rejected", reviewNote: "Pin the source." });
    });
    await expect(client.reviewQueue("secret")).resolves.toEqual([queued]);
    await expect(
      client.review(receipt.id, "reject", "secret", "Pin the source."),
    ).resolves.toMatchObject({
      status: "rejected",
    });
    expect(
      requests.every((request) => request.headers.get("authorization") === "Bearer secret"),
    ).toBe(true);
  });
});
