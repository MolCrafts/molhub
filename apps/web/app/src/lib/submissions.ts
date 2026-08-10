import type { ManifestDocument, ManifestIssue } from "@molcrafts/molhub/core";

export type SubmissionStatus = "pending" | "reviewing" | "accepted" | "rejected";

export interface SubmissionReceipt {
  readonly id: string;
  readonly coordinate: string;
  readonly status: SubmissionStatus;
  readonly reviewNote: string | null;
  readonly pullRequestUrl: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface ReviewerSubmission extends SubmissionReceipt {
  readonly manifest: ManifestDocument;
  readonly manifestYaml: string;
  readonly contributor: { readonly name?: string };
}

export class SubmissionApiError extends Error {
  constructor(
    message: string,
    readonly issues: readonly ManifestIssue[] = [],
  ) {
    super(message);
  }
}

export class SubmissionClient {
  constructor(
    private readonly baseUrl = process.env.PUBLIC_MOLHUB_API_URL ?? "http://localhost:8787",
    private readonly fetcher = globalThis.fetch,
  ) {}

  async submit(
    manifest: ManifestDocument,
    contributor: { readonly name?: string; readonly email?: string } = {},
  ): Promise<SubmissionReceipt> {
    const response = await this.fetcher(`${this.baseUrl.replace(/\/$/, "")}/v1/submissions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ manifest, contributor }),
    });
    const payload: unknown = await response.json();
    if (!response.ok) {
      const issues = Array.isArray(objectValue(payload, "issues"))
        ? (objectValue(payload, "issues") as ManifestIssue[])
        : [];
      const message = objectValue(payload, "message");
      throw new SubmissionApiError(
        typeof message === "string" ? message : `Submission failed with HTTP ${response.status}.`,
        issues,
      );
    }
    if (!isReceipt(payload))
      throw new SubmissionApiError("The submission API returned an invalid receipt.");
    return payload;
  }

  async get(id: string): Promise<SubmissionReceipt> {
    const response = await this.fetcher(
      `${this.baseUrl.replace(/\/$/, "")}/v1/submissions/${encodeURIComponent(id)}`,
      { headers: { accept: "application/json" } },
    );
    const payload: unknown = await response.json();
    if (!response.ok) {
      const message = objectValue(payload, "message");
      throw new SubmissionApiError(
        typeof message === "string"
          ? message
          : `Status lookup failed with HTTP ${response.status}.`,
      );
    }
    if (!isReceipt(payload))
      throw new SubmissionApiError("The submission API returned an invalid receipt.");
    return payload;
  }

  async reviewQueue(
    adminToken: string,
    status: SubmissionStatus | "all" = "pending",
  ): Promise<readonly ReviewerSubmission[]> {
    const query = status === "all" ? "" : `?status=${encodeURIComponent(status)}`;
    const response = await this.fetcher(
      `${this.baseUrl.replace(/\/$/, "")}/v1/review/submissions${query}`,
      { headers: { accept: "application/json", authorization: `Bearer ${adminToken}` } },
    );
    const payload: unknown = await response.json();
    if (!response.ok) throw responseError(payload, response.status, "Review queue failed");
    if (!Array.isArray(payload) || !payload.every(isReviewerSubmission)) {
      throw new SubmissionApiError("The submission API returned an invalid review queue.");
    }
    return payload;
  }

  async review(
    id: string,
    decision: "approve" | "reject",
    adminToken: string,
    note?: string,
  ): Promise<SubmissionReceipt> {
    const response = await this.fetcher(
      `${this.baseUrl.replace(/\/$/, "")}/v1/submissions/${encodeURIComponent(id)}/review`,
      {
        method: "POST",
        headers: {
          accept: "application/json",
          authorization: `Bearer ${adminToken}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({ decision, ...(note?.trim() ? { note: note.trim() } : {}) }),
      },
    );
    const payload: unknown = await response.json();
    if (!response.ok) throw responseError(payload, response.status, "Review failed");
    if (!isReceipt(payload))
      throw new SubmissionApiError("The submission API returned an invalid review result.");
    return payload;
  }
}

function objectValue(input: unknown, key: string): unknown {
  return typeof input === "object" && input !== null ? Reflect.get(input, key) : undefined;
}

function isReceipt(input: unknown): input is SubmissionReceipt {
  return (
    typeof objectValue(input, "id") === "string" &&
    typeof objectValue(input, "coordinate") === "string" &&
    typeof objectValue(input, "status") === "string"
  );
}

function isReviewerSubmission(input: unknown): input is ReviewerSubmission {
  return (
    isReceipt(input) &&
    typeof objectValue(input, "manifest") === "object" &&
    typeof objectValue(input, "manifestYaml") === "string" &&
    typeof objectValue(input, "contributor") === "object"
  );
}

function responseError(payload: unknown, status: number, fallback: string): SubmissionApiError {
  const message = objectValue(payload, "message");
  return new SubmissionApiError(
    typeof message === "string" ? message : `${fallback} with HTTP ${status}.`,
  );
}
