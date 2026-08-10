import type { ManifestDocument } from "@molcrafts/molhub/core";

export type SubmissionStatus = "pending" | "reviewing" | "accepted" | "rejected";

export interface Contributor {
  readonly name?: string;
  readonly email?: string;
}

export interface Submission {
  readonly id: string;
  readonly coordinate: string;
  readonly manifest: ManifestDocument;
  readonly manifestYaml: string;
  readonly status: SubmissionStatus;
  readonly contributor: Contributor;
  readonly reviewNote: string | null;
  readonly pullRequestUrl: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface PublicSubmission {
  readonly id: string;
  readonly coordinate: string;
  readonly status: SubmissionStatus;
  readonly reviewNote: string | null;
  readonly pullRequestUrl: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface ReviewerSubmission extends PublicSubmission {
  readonly manifest: ManifestDocument;
  readonly manifestYaml: string;
  readonly contributor: { readonly name?: string };
}

export function publicSubmission(submission: Submission): PublicSubmission {
  return {
    id: submission.id,
    coordinate: submission.coordinate,
    status: submission.status,
    reviewNote: submission.reviewNote,
    pullRequestUrl: submission.pullRequestUrl,
    createdAt: submission.createdAt,
    updatedAt: submission.updatedAt,
  };
}

export function reviewerSubmission(submission: Submission): ReviewerSubmission {
  return {
    ...publicSubmission(submission),
    manifest: submission.manifest,
    manifestYaml: submission.manifestYaml,
    contributor: submission.contributor.name ? { name: submission.contributor.name } : {},
  };
}
