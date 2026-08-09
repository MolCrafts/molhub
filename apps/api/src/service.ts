import {
  type ManifestIssue,
  ManifestValidator,
  manifestCoordinate,
  serializeManifest,
} from "@molcrafts/molhub/core";

import {
  type Contributor,
  type PublicSubmission,
  type ReviewerSubmission,
  type Submission,
  type SubmissionStatus,
  publicSubmission,
  reviewerSubmission,
} from "./domain.js";
import type { RegistryPublisher } from "./publisher.js";
import type { SubmissionRepository } from "./repository.js";

export class SubmissionValidationError extends Error {
  constructor(readonly issues: readonly ManifestIssue[]) {
    super("Manifest validation failed.");
  }
}

export class SubmissionConflict extends Error {}
export class SubmissionNotFound extends Error {}

export class SubmissionService {
  constructor(
    private readonly repository: SubmissionRepository,
    private readonly publisher: RegistryPublisher,
    private readonly validator = new ManifestValidator(),
  ) {}

  async create(manifest: unknown, contributor: Contributor = {}): Promise<PublicSubmission> {
    const validation = this.validator.validate(manifest);
    if (!validation.ok) throw new SubmissionValidationError(validation.issues);
    const coordinate = manifestCoordinate(validation.value).canonical;
    const active = await this.repository.findActiveByCoordinate(coordinate);
    if (active) throw new SubmissionConflict(`${coordinate} already has an active submission.`);

    const now = new Date().toISOString();
    const submission: Submission = {
      id: crypto.randomUUID(),
      coordinate,
      manifest: validation.value,
      manifestYaml: serializeManifest(validation.value),
      status: "pending",
      contributor,
      reviewNote: null,
      pullRequestUrl: null,
      createdAt: now,
      updatedAt: now,
    };
    await this.repository.insert(submission);
    return publicSubmission(submission);
  }

  async get(id: string): Promise<PublicSubmission> {
    const submission = await this.repository.get(id);
    if (!submission) throw new SubmissionNotFound(`Submission ${id} does not exist.`);
    return publicSubmission(submission);
  }

  async listForReview(status?: SubmissionStatus): Promise<readonly ReviewerSubmission[]> {
    return (await this.repository.list(status)).map(reviewerSubmission);
  }

  async approve(id: string, note?: string): Promise<PublicSubmission> {
    const submission = await this.repository.get(id);
    if (!submission) throw new SubmissionNotFound(`Submission ${id} does not exist.`);
    if (submission.status !== "pending") {
      throw new SubmissionConflict(`Submission ${id} is already ${submission.status}.`);
    }
    const publication = await this.publisher.publish({
      submissionId: submission.id,
      coordinate: submission.coordinate,
      manifestYaml: submission.manifestYaml,
    });
    return publicSubmission(
      await this.repository.updateReview(id, "reviewing", {
        ...(note === undefined ? {} : { note }),
        pullRequestUrl: publication.pullRequestUrl,
      }),
    );
  }

  async reject(id: string, note: string): Promise<PublicSubmission> {
    const submission = await this.repository.get(id);
    if (!submission) throw new SubmissionNotFound(`Submission ${id} does not exist.`);
    if (submission.status !== "pending") {
      throw new SubmissionConflict(`Submission ${id} is already ${submission.status}.`);
    }
    return publicSubmission(await this.repository.updateReview(id, "rejected", { note }));
  }

  async acceptPullRequest(url: string): Promise<void> {
    await this.repository.markAcceptedByPullRequest(url);
  }
}
