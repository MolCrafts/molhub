import { describe, expect, it } from "vitest";

import type { Submission } from "../src/domain.js";
import type { PublicationResult, PublishRequest, RegistryPublisher } from "../src/publisher.js";
import type { SubmissionRepository } from "../src/repository.js";
import { SubmissionService } from "../src/service.js";

describe("SubmissionService", () => {
  it("publishes an approved manifest through the injected registry adapter", async () => {
    const repository = new MemoryRepository();
    const publisher = new RecordingPublisher();
    const service = new SubmissionService(repository, publisher);
    const created = await service.create(manifest("approve"));
    const reviewed = await service.approve(created.id, "Ready to review.");

    expect(reviewed.status).toBe("reviewing");
    expect(reviewed.pullRequestUrl).toBe("https://github.test/pull/1");
    expect(publisher.requests[0]?.coordinate).toBe("dataset:lab/approve@v1");
  });
});

class RecordingPublisher implements RegistryPublisher {
  readonly requests: PublishRequest[] = [];

  async publish(request: PublishRequest): Promise<PublicationResult> {
    this.requests.push(request);
    return { pullRequestUrl: "https://github.test/pull/1" };
  }
}

class MemoryRepository implements SubmissionRepository {
  readonly #submissions = new Map<string, Submission>();

  async insert(submission: Submission): Promise<void> {
    this.#submissions.set(submission.id, submission);
  }

  async get(id: string): Promise<Submission | null> {
    return this.#submissions.get(id) ?? null;
  }

  async list(status?: Submission["status"]): Promise<readonly Submission[]> {
    return [...this.#submissions.values()].filter(
      (submission) => status === undefined || submission.status === status,
    );
  }

  async findActiveByCoordinate(coordinate: string): Promise<Submission | null> {
    return (
      [...this.#submissions.values()].find((submission) => submission.coordinate === coordinate) ??
      null
    );
  }

  async updateReview(
    id: string,
    status: Submission["status"],
    values: { readonly note?: string | null; readonly pullRequestUrl?: string | null },
  ): Promise<Submission> {
    const current = this.#submissions.get(id);
    if (!current) throw new Error("Missing submission.");
    const updated: Submission = {
      ...current,
      status,
      reviewNote: values.note === undefined ? current.reviewNote : values.note,
      pullRequestUrl:
        values.pullRequestUrl === undefined ? current.pullRequestUrl : values.pullRequestUrl,
      updatedAt: new Date().toISOString(),
    };
    this.#submissions.set(id, updated);
    return updated;
  }

  async markAcceptedByPullRequest(pullRequestUrl: string): Promise<void> {
    for (const [id, submission] of this.#submissions) {
      if (submission.pullRequestUrl === pullRequestUrl) {
        this.#submissions.set(id, { ...submission, status: "accepted" });
      }
    }
  }
}

function manifest(name: string): object {
  return {
    schema_version: 1,
    kind: "dataset",
    namespace: "lab",
    name,
    version: "v1",
    title: "Sample",
    doi: "10.0000/sample",
    artifacts: [
      {
        role: "main",
        filename: "sample.xyz",
        size: 4,
        locators: ["https://example.test/sample.xyz"],
      },
    ],
  };
}
