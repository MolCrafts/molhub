import type { Contributor, SubmissionStatus } from "./domain.js";
import {
  SubmissionConflict,
  SubmissionNotFound,
  type SubmissionService,
  SubmissionValidationError,
} from "./service.js";

const BODY_LIMIT = 64 * 1024;

export interface ApiSecrets {
  readonly adminToken: string | null;
  readonly webhookSecret: string | null;
  readonly rateLimiter: RateLimit | null;
}

export class SubmissionApi {
  constructor(
    private readonly service: SubmissionService,
    private readonly webOrigin: string,
    private readonly secrets: ApiSecrets,
  ) {}

  async handle(request: Request): Promise<Response> {
    if (request.method === "OPTIONS")
      return this.cors(new Response(null, { status: 204 }), request);
    try {
      const response = await this.route(request);
      return this.cors(response, request);
    } catch (error) {
      return this.cors(this.errorResponse(error), request);
    }
  }

  private async route(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ status: "ok" });
    }
    if (request.method === "POST" && url.pathname === "/v1/submissions") {
      const limited = await this.enforceSubmissionLimit(request);
      if (limited) return limited;
      const body = await jsonBody(request);
      const manifest = objectValue(body, "manifest");
      if (manifest === undefined)
        return problem(400, "missing_manifest", "Body must contain manifest.");
      const contributor = readContributor(objectValue(body, "contributor"));
      return json(await this.service.create(manifest, contributor), 201);
    }

    if (request.method === "GET" && url.pathname === "/v1/review/submissions") {
      await this.authorize(request, this.secrets.adminToken, "admin token");
      const statusValue = url.searchParams.get("status");
      const status = statusValue === null ? undefined : readStatus(statusValue);
      return json(await this.service.listForReview(status));
    }

    const statusMatch = url.pathname.match(/^\/v1\/submissions\/([0-9a-f-]+)$/i);
    if (request.method === "GET" && statusMatch?.[1]) {
      return json(await this.service.get(statusMatch[1]));
    }

    const reviewMatch = url.pathname.match(/^\/v1\/submissions\/([0-9a-f-]+)\/review$/i);
    if (request.method === "POST" && reviewMatch?.[1]) {
      await this.authorize(request, this.secrets.adminToken, "admin token");
      const body = await jsonBody(request);
      const decision = objectValue(body, "decision");
      const noteValue = objectValue(body, "note");
      const note = typeof noteValue === "string" ? noteValue.trim() : undefined;
      if (decision === "approve") return json(await this.service.approve(reviewMatch[1], note));
      if (decision === "reject") {
        if (!note) return problem(400, "missing_note", "A rejection must explain what to change.");
        return json(await this.service.reject(reviewMatch[1], note));
      }
      return problem(400, "invalid_decision", "Decision must be approve or reject.");
    }

    if (request.method === "POST" && url.pathname === "/v1/github/webhook") {
      return this.githubWebhook(request);
    }
    return problem(404, "not_found", "Route not found.");
  }

  private async githubWebhook(request: Request): Promise<Response> {
    const secret = this.secrets.webhookSecret;
    if (!secret) return problem(503, "webhook_not_configured", "GitHub webhook is not configured.");
    const body = await boundedBody(request);
    const signature = request.headers.get("x-hub-signature-256");
    if (!signature || !(await verifySignature(body, signature, secret))) {
      return problem(401, "invalid_signature", "Webhook signature is invalid.");
    }
    if (request.headers.get("x-github-event") !== "pull_request")
      return new Response(null, { status: 204 });
    const payload: unknown = JSON.parse(body);
    const pullRequest = objectValue(payload, "pull_request");
    if (
      objectValue(payload, "action") === "closed" &&
      objectValue(pullRequest, "merged") === true &&
      typeof objectValue(pullRequest, "html_url") === "string"
    ) {
      await this.service.acceptPullRequest(objectValue(pullRequest, "html_url") as string);
    }
    return new Response(null, { status: 204 });
  }

  private async authorize(request: Request, expected: string | null, name: string): Promise<void> {
    if (!expected) throw new HttpError(503, "auth_not_configured", `${name} is not configured.`);
    const header = request.headers.get("authorization") ?? "";
    const provided = header.startsWith("Bearer ") ? header.slice(7) : "";
    if (!(await secureEqual(provided, expected))) {
      throw new HttpError(401, "unauthorized", "Authorization failed.");
    }
  }

  private async enforceSubmissionLimit(request: Request): Promise<Response | null> {
    if (!this.secrets.rateLimiter) {
      throw new HttpError(
        503,
        "rate_limit_not_configured",
        "Submission protection is unavailable.",
      );
    }
    const fingerprint = await actorFingerprint(request);
    const { success } = await this.secrets.rateLimiter.limit({ key: fingerprint });
    if (success) return null;
    return Response.json(
      {
        error: "rate_limited",
        message: "Too many submissions. Wait one minute before trying again.",
      },
      {
        status: 429,
        headers: { "cache-control": "no-store", "retry-after": "60" },
      },
    );
  }

  private errorResponse(error: unknown): Response {
    if (error instanceof HttpError) return problem(error.status, error.code, error.message);
    if (error instanceof SubmissionValidationError) {
      return json({ error: "invalid_manifest", issues: error.issues }, 422);
    }
    if (error instanceof SubmissionConflict) return problem(409, "conflict", error.message);
    if (error instanceof SubmissionNotFound)
      return problem(404, "submission_not_found", error.message);
    if (error instanceof SyntaxError)
      return problem(400, "invalid_json", "Request body is not valid JSON.");
    const kind = error instanceof Error ? error.name : typeof error;
    console.error(JSON.stringify({ message: "request failed", error: kind }));
    return problem(500, "internal_error", "Internal server error.");
  }

  private cors(response: Response, request: Request): Response {
    const origin = request.headers.get("origin");
    if (origin !== this.webOrigin) return response;
    const headers = new Headers(response.headers);
    headers.set("access-control-allow-origin", this.webOrigin);
    headers.set("access-control-allow-methods", "GET, POST, OPTIONS");
    headers.set(
      "access-control-allow-headers",
      "authorization, content-type, x-github-event, x-hub-signature-256",
    );
    headers.set("vary", "Origin");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  }
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status, headers: { "cache-control": "no-store" } });
}

function problem(status: number, error: string, message: string): Response {
  return json({ error, message }, status);
}

async function jsonBody(request: Request): Promise<unknown> {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) {
    throw new HttpError(415, "unsupported_media_type", "Use application/json.");
  }
  return JSON.parse(await boundedBody(request));
}

async function boundedBody(request: Request): Promise<string> {
  const declared = Number(request.headers.get("content-length") ?? 0);
  if (declared > BODY_LIMIT)
    throw new HttpError(413, "body_too_large", "Request body exceeds 64 KiB.");
  if (!request.body) return "";
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let total = 0;
  let text = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > BODY_LIMIT)
      throw new HttpError(413, "body_too_large", "Request body exceeds 64 KiB.");
    text += decoder.decode(value, { stream: true });
  }
  return text + decoder.decode();
}

function readContributor(input: unknown): Contributor {
  if (input === undefined || input === null) return {};
  if (typeof input !== "object")
    throw new HttpError(400, "invalid_contributor", "Contributor must be an object.");
  const name = objectValue(input, "name");
  const email = objectValue(input, "email");
  if (name !== undefined && typeof name !== "string") {
    throw new HttpError(400, "invalid_contributor", "Contributor name must be text.");
  }
  if (email !== undefined && (typeof email !== "string" || !/^\S+@\S+\.\S+$/.test(email))) {
    throw new HttpError(400, "invalid_contributor", "Contributor email is invalid.");
  }
  return {
    ...(typeof name === "string" && name.trim() ? { name: name.trim().slice(0, 120) } : {}),
    ...(typeof email === "string" ? { email: email.trim().slice(0, 254) } : {}),
  };
}

function objectValue(input: unknown, key: string): unknown {
  return typeof input === "object" && input !== null ? Reflect.get(input, key) : undefined;
}

function readStatus(value: string): SubmissionStatus {
  if (
    value === "pending" ||
    value === "reviewing" ||
    value === "accepted" ||
    value === "rejected"
  ) {
    return value;
  }
  throw new HttpError(400, "invalid_status", "Unknown submission status.");
}

async function actorFingerprint(request: Request): Promise<string> {
  const actor = [
    request.headers.get("cf-connecting-ip") ?? "anonymous",
    request.headers.get("user-agent") ?? "unknown-agent",
  ].join("\n");
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(actor));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function secureEqual(provided: string, expected: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return timingSafeEqual(providedHash, expectedHash);
}

async function verifySignature(body: string, signature: string, secret: string): Promise<boolean> {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const expected = hexBytes(signature.replace(/^sha256=/, ""));
  if (expected.byteLength !== 32) return false;
  return crypto.subtle.verify("HMAC", key, expected, encoder.encode(body));
}

function timingSafeEqual(left: ArrayBuffer, right: ArrayBuffer): boolean {
  const method = Reflect.get(crypto.subtle, "timingSafeEqual");
  if (typeof method !== "function") throw new Error("Workers timingSafeEqual is unavailable.");
  return Boolean(Reflect.apply(method, crypto.subtle, [left, right]));
}

function hexBytes(hex: string): ArrayBuffer {
  if (!/^[0-9a-f]+$/i.test(hex) || hex.length % 2 !== 0) return new ArrayBuffer(0);
  const buffer = new ArrayBuffer(hex.length / 2);
  const bytes = new Uint8Array(buffer);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Number.parseInt(hex.slice(index * 2, index * 2 + 2), 16);
  }
  return buffer;
}
