import { describe, expect, it } from "vitest";

import type { Submission } from "../src/domain.js";
import type { PublicationResult, PublishRequest, RegistryPublisher } from "../src/publisher.js";
import type { SubmissionRepository } from "../src/repository.js";
import { SubmissionConflict, SubmissionService } from "../src/service.js";

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
  it("allows only one concurrent submission per coordinate", async () => {
    const service = new SubmissionService(new MemoryRepository(), new RecordingPublisher());
    const results = await Promise.allSettled([
      service.create(manifest("race")),
      service.create(manifest("race")),
    ]);
    expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
    const failed = results.find((result) => result.status === "rejected");
    expect(failed?.status === "rejected" && failed.reason).toBeInstanceOf(SubmissionConflict);
  });

  it("claims approval before publishing so rejection cannot race it", async () => {
    let release!: () => void;
    let started!: () => void;
    const waiting = new Promise<void>((resolve) => {
      release = resolve;
    });
    const entered = new Promise<void>((resolve) => {
      started = resolve;
    });
    const publisher: RegistryPublisher = {
      async publish() {
        started();
        await waiting;
        return { pullRequestUrl: "https://github.test/pull/1" };
      },
    };
    const service = new SubmissionService(new MemoryRepository(), publisher);
    const created = await service.create(manifest("decision-race"));
    const approving = service.approve(created.id);
    await entered;
    try {
      await expect(service.reject(created.id, "reject")).rejects.toBeInstanceOf(SubmissionConflict);
    } finally {
      release();
    }
    expect((await approving).status).toBe("reviewing");
  });

  it("keeps an interrupted publication resumable and returns completed approvals", async () => {
    const repository = new MemoryRepository();
    const publisher = new RecordingPublisher();
    const service = new SubmissionService(repository, {
      async publish(request) {
        if (publisher.requests.length === 0) {
          publisher.requests.push(request);
          throw new Error("connection lost");
        }
        return publisher.publish(request);
      },
    });
    const created = await service.create(manifest("retry"));
    await expect(service.approve(created.id)).rejects.toThrow("connection lost");
    expect((await service.get(created.id)).status).toBe("reviewing");
    const reviewed = await service.approve(created.id);
    expect(reviewed.pullRequestUrl).toBe("https://github.test/pull/1");
    expect(await service.approve(created.id)).toEqual(reviewed);
    expect(publisher.requests).toHaveLength(2);
  });

  it("marks a previously merged publication accepted on recovery", async () => {
    const service = new SubmissionService(new MemoryRepository(), {
      async publish() {
        return { pullRequestUrl: "https://github.test/pull/merged", merged: true };
      },
    });
    const created = await service.create(manifest("merged-retry"));
    expect(await service.approve(created.id)).toMatchObject({ status: "accepted" });
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
  readonly #merged = new Set<string>();

  async insert(submission: Submission): Promise<boolean> {
    if (
      [...this.#submissions.values()].some(
        (entry) => entry.coordinate === submission.coordinate && entry.status !== "rejected",
      )
    )
      return false;
    this.#submissions.set(submission.id, submission);
    return true;
  }

  async get(id: string): Promise<Submission | null> {
    return this.#submissions.get(id) ?? null;
  }

  async list(status?: Submission["status"]): Promise<readonly Submission[]> {
    return [...this.#submissions.values()].filter(
      (submission) => status === undefined || submission.status === status,
    );
  }

  async transition(
    id: string,
    expected: "pending" | "reviewing",
    status: "reviewing" | "rejected",
    values: { readonly note?: string | null; readonly pullRequestUrl?: string | null },
  ): Promise<Submission | null> {
    const current = this.#submissions.get(id);
    if (!current || current.status !== expected) return null;
    const updated: Submission = {
      ...current,
      status:
        status === "reviewing" &&
        this.#merged.has(values.pullRequestUrl ?? current.pullRequestUrl ?? "")
          ? "accepted"
          : status,
      reviewNote: values.note === undefined ? current.reviewNote : values.note,
      pullRequestUrl:
        values.pullRequestUrl === undefined ? current.pullRequestUrl : values.pullRequestUrl,
      updatedAt: new Date().toISOString(),
    };
    this.#submissions.set(id, updated);
    return updated;
  }

  async markAcceptedByPullRequest(pullRequestUrl: string): Promise<void> {
    this.#merged.add(pullRequestUrl);
    for (const [id, submission] of this.#submissions) {
      if (submission.pullRequestUrl === pullRequestUrl) {
        this.#submissions.set(id, { ...submission, status: "accepted" });
      }
    }
  }
}

function manifest(name: string): object {
  return {
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
