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
    if (!(await this.repository.insert(submission))) {
      throw new SubmissionConflict(`${coordinate} already has an active submission.`);
    }
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
    let submission = await this.repository.get(id);
    if (!submission) throw new SubmissionNotFound(`Submission ${id} does not exist.`);
    if (submission.status === "pending") {
      submission =
        (await this.repository.transition(id, "pending", "reviewing", {
          ...(note === undefined ? {} : { note }),
        })) ?? (await this.repository.get(id));
    }
    if (!submission || submission.status === "pending" || submission.status === "rejected") {
      throw new SubmissionConflict(`Submission ${id} cannot be approved.`);
    }
    if (submission.pullRequestUrl) return publicSubmission(submission);
    const publication = await this.publisher.publish({
      submissionId: submission.id,
      coordinate: submission.coordinate,
      manifestYaml: submission.manifestYaml,
    });
    if (publication.merged)
      await this.repository.markAcceptedByPullRequest(publication.pullRequestUrl);
    const updated =
      (await this.repository.transition(id, "reviewing", "reviewing", {
        pullRequestUrl: publication.pullRequestUrl,
      })) ?? (await this.repository.get(id));
    if (!updated || updated.pullRequestUrl !== publication.pullRequestUrl) {
      throw new SubmissionConflict(`Submission ${id} changed during publication.`);
    }
    return publicSubmission(updated);
  }

  async reject(id: string, note: string): Promise<PublicSubmission> {
    const updated = await this.repository.transition(id, "pending", "rejected", { note });
    if (updated) return publicSubmission(updated);
    const submission = await this.repository.get(id);
    if (!submission) throw new SubmissionNotFound(`Submission ${id} does not exist.`);
    throw new SubmissionConflict(`Submission ${id} is already ${submission.status}.`);
  }

  async acceptPullRequest(url: string): Promise<void> {
    await this.repository.markAcceptedByPullRequest(url);
  }
}
