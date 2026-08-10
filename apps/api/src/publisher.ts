import { Coordinate } from "@molcrafts/molhub/core";

export interface PublishRequest {
  readonly submissionId: string;
  readonly coordinate: string;
  readonly manifestYaml: string;
}

export interface PublicationResult {
  readonly pullRequestUrl: string;
}

export interface RegistryPublisher {
  publish(request: PublishRequest): Promise<PublicationResult>;
}

export interface GitHubPublisherOptions {
  readonly token: string;
  readonly repository: string;
  readonly baseBranch: string;
  readonly fetch?: typeof globalThis.fetch;
}

export class GitHubRegistryPublisher implements RegistryPublisher {
  readonly #fetch: typeof globalThis.fetch;

  constructor(private readonly options: GitHubPublisherOptions) {
    this.#fetch = options.fetch ?? globalThis.fetch;
  }

  async publish(request: PublishRequest): Promise<PublicationResult> {
    if (!this.options.token) throw new Error("GITHUB_TOKEN is not configured.");
    const coordinate = Coordinate.parse(request.coordinate);
    const branch = `molhub/submission-${request.submissionId}`;
    const path = `artifacts/${coordinate.manifestPath}`;
    const base = await this.github(`/git/ref/heads/${encodeURIComponent(this.options.baseBranch)}`);
    const sha = requiredString(objectValue(objectValue(base, "object"), "sha"), "base ref sha");

    const existing = await this.github(
      `/contents/${path}?ref=${encodeURIComponent(this.options.baseBranch)}`,
      {
        allowNotFound: true,
      },
    );
    if (existing !== null)
      throw new Error(`${coordinate.canonical} already exists in the registry.`);

    await this.github("/git/refs", {
      method: "POST",
      body: { ref: `refs/heads/${branch}`, sha },
    });
    await this.github(`/contents/${path}`, {
      method: "PUT",
      body: {
        message: `Add ${coordinate.canonical}`,
        content: base64(request.manifestYaml),
        branch,
      },
    });
    const pull = await this.github("/pulls", {
      method: "POST",
      body: {
        title: `Add ${coordinate.canonical}`,
        head: branch,
        base: this.options.baseBranch,
        body: `Submitted through MolHub.\n\nSubmission ID: \`${request.submissionId}\``,
      },
    });
    return { pullRequestUrl: requiredString(objectValue(pull, "html_url"), "pull request URL") };
  }

  private async github(
    path: string,
    options: {
      readonly method?: "GET" | "POST" | "PUT";
      readonly body?: Record<string, unknown>;
      readonly allowNotFound?: boolean;
    } = {},
  ): Promise<unknown | null> {
    const response = await this.#fetch(
      `https://api.github.com/repos/${this.options.repository}${path}`,
      {
        method: options.method ?? "GET",
        headers: {
          accept: "application/vnd.github+json",
          authorization: `Bearer ${this.options.token}`,
          "content-type": "application/json",
          "user-agent": "molhub-api/0.1",
          "x-github-api-version": "2022-11-28",
        },
        ...(options.body ? { body: JSON.stringify(options.body) } : {}),
      },
    );
    if (options.allowNotFound && response.status === 404) return null;
    if (!response.ok) {
      const detail = await boundedText(response, 16 * 1024);
      throw new Error(`GitHub ${path} returned HTTP ${response.status}: ${detail}`);
    }
    const text = await boundedText(response, 1024 * 1024);
    try {
      return JSON.parse(text);
    } catch (error) {
      throw new Error(`GitHub ${path} returned invalid JSON.`, { cause: error });
    }
  }
}

function base64(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function objectValue(input: unknown, key: string): unknown {
  return typeof input === "object" && input !== null ? Reflect.get(input, key) : undefined;
}

function requiredString(input: unknown, name: string): string {
  if (typeof input !== "string" || !input) throw new Error(`GitHub response omitted ${name}.`);
  return input;
}

async function boundedText(response: Response, limit: number): Promise<string> {
  const declared = Number(response.headers.get("content-length") ?? 0);
  if (declared > limit) throw new Error(`GitHub response exceeds ${limit} bytes.`);
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > limit) {
      await reader.cancel();
      throw new Error(`GitHub response exceeds ${limit} bytes.`);
    }
    text += decoder.decode(value, { stream: true });
  }
  return text + decoder.decode();
}
