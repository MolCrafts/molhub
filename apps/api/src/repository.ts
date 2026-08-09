import type { ManifestDocument } from "@molcrafts/molhub/core";
import type { Contributor, Submission, SubmissionStatus } from "./domain.js";

export interface SubmissionRepository {
  insert(submission: Submission): Promise<void>;
  get(id: string): Promise<Submission | null>;
  list(status?: SubmissionStatus): Promise<readonly Submission[]>;
  findActiveByCoordinate(coordinate: string): Promise<Submission | null>;
  updateReview(
    id: string,
    status: SubmissionStatus,
    values: { readonly note?: string | null; readonly pullRequestUrl?: string | null },
  ): Promise<Submission>;
  markAcceptedByPullRequest(pullRequestUrl: string): Promise<void>;
}

interface SubmissionRow {
  id: string;
  coordinate: string;
  manifest_json: string;
  manifest_yaml: string;
  status: SubmissionStatus;
  contributor_name: string | null;
  contributor_email: string | null;
  review_note: string | null;
  pull_request_url: string | null;
  created_at: string;
  updated_at: string;
}

export class D1SubmissionRepository implements SubmissionRepository {
  constructor(private readonly database: D1Database) {}

  async insert(submission: Submission): Promise<void> {
    await this.database
      .prepare(
        `INSERT INTO submissions (
          id, coordinate, manifest_json, manifest_yaml, status,
          contributor_name, contributor_email, review_note, pull_request_url,
          created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      )
      .bind(
        submission.id,
        submission.coordinate,
        JSON.stringify(submission.manifest),
        submission.manifestYaml,
        submission.status,
        submission.contributor.name ?? null,
        submission.contributor.email ?? null,
        submission.reviewNote,
        submission.pullRequestUrl,
        submission.createdAt,
        submission.updatedAt,
      )
      .run();
  }

  async get(id: string): Promise<Submission | null> {
    const row = await this.database
      .prepare("SELECT * FROM submissions WHERE id = ?")
      .bind(id)
      .first<SubmissionRow>();
    return row ? D1SubmissionRepository.toDomain(row) : null;
  }

  async findActiveByCoordinate(coordinate: string): Promise<Submission | null> {
    const row = await this.database
      .prepare(
        "SELECT * FROM submissions WHERE coordinate = ? AND status IN ('pending', 'reviewing', 'accepted') ORDER BY created_at DESC LIMIT 1",
      )
      .bind(coordinate)
      .first<SubmissionRow>();
    return row ? D1SubmissionRepository.toDomain(row) : null;
  }

  async list(status?: SubmissionStatus): Promise<readonly Submission[]> {
    const statement = status
      ? this.database
          .prepare("SELECT * FROM submissions WHERE status = ? ORDER BY created_at DESC LIMIT 100")
          .bind(status)
      : this.database.prepare("SELECT * FROM submissions ORDER BY created_at DESC LIMIT 100");
    const result = await statement.all<SubmissionRow>();
    return result.results.map(D1SubmissionRepository.toDomain);
  }

  async updateReview(
    id: string,
    status: SubmissionStatus,
    values: { readonly note?: string | null; readonly pullRequestUrl?: string | null },
  ): Promise<Submission> {
    const current = await this.get(id);
    if (!current) throw new Error(`Submission ${id} does not exist.`);
    const updatedAt = new Date().toISOString();
    await this.database
      .prepare(
        "UPDATE submissions SET status = ?, review_note = ?, pull_request_url = ?, updated_at = ? WHERE id = ?",
      )
      .bind(
        status,
        values.note === undefined ? current.reviewNote : values.note,
        values.pullRequestUrl === undefined ? current.pullRequestUrl : values.pullRequestUrl,
        updatedAt,
        id,
      )
      .run();
    const updated = await this.get(id);
    if (!updated) throw new Error(`Submission ${id} disappeared after update.`);
    return updated;
  }

  async markAcceptedByPullRequest(pullRequestUrl: string): Promise<void> {
    await this.database
      .prepare(
        "UPDATE submissions SET status = 'accepted', updated_at = ? WHERE pull_request_url = ? AND status = 'reviewing'",
      )
      .bind(new Date().toISOString(), pullRequestUrl)
      .run();
  }

  private static toDomain(row: SubmissionRow): Submission {
    const contributor: Contributor = {
      ...(row.contributor_name ? { name: row.contributor_name } : {}),
      ...(row.contributor_email ? { email: row.contributor_email } : {}),
    };
    return {
      id: row.id,
      coordinate: row.coordinate,
      manifest: JSON.parse(row.manifest_json) as ManifestDocument,
      manifestYaml: row.manifest_yaml,
      status: row.status,
      contributor,
      reviewNote: row.review_note,
      pullRequestUrl: row.pull_request_url,
      createdAt: row.created_at,
      updatedAt: row.updated_at,
    };
  }
}
