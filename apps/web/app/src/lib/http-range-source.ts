export const DEFAULT_FULL_DOWNLOAD_LIMIT = 16 * 1024 * 1024;

export interface RemoteObjectMetadata {
  size: number | null;
  mediaType: string | null;
  etag: string | null;
  lastModified: string | null;
  acceptsRanges: boolean;
}

export class RangeUnavailableError extends Error {
  override readonly name = "RangeUnavailableError";
}

export class InvalidRangeResponseError extends Error {
  override readonly name = "InvalidRangeResponseError";
}

export interface HttpRangeSourceOptions {
  fetch?: typeof fetch;
  maxFullDownloadBytes?: number;
}

/**
 * Bounded random access for remote records. A server that ignores Range may
 * only fall back to a full body when Content-Length proves it fits the budget.
 */
export class HttpRangeSource {
  readonly url: string;
  readonly #fetch: typeof fetch;
  readonly #maxFullDownloadBytes: number;
  #metadata: RemoteObjectMetadata | null = null;

  constructor(url: string, options: HttpRangeSourceOptions = {}) {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      throw new TypeError("HttpRangeSource requires an HTTP(S) URL");
    }
    this.url = parsed.href;
    this.#fetch = options.fetch ?? globalThis.fetch;
    this.#maxFullDownloadBytes = options.maxFullDownloadBytes ?? DEFAULT_FULL_DOWNLOAD_LIMIT;
  }

  async probe(signal?: AbortSignal): Promise<RemoteObjectMetadata> {
    if (this.#metadata) return this.#metadata;

    const head = await this.#fetch(this.url, {
      method: "HEAD",
      credentials: "omit",
      redirect: "follow",
      signal,
    });
    if (head.ok) {
      this.#metadata = metadataFromHeaders(head.headers);
      if (this.#metadata.acceptsRanges) return this.#metadata;
    }

    const range = await this.#fetch(this.url, {
      headers: { Range: "bytes=0-0" },
      credentials: "omit",
      redirect: "follow",
      signal,
    });
    if (range.status === 206) {
      const parsedRange = parseContentRange(range.headers.get("content-range"));
      await range.body?.cancel();
      this.#metadata = {
        ...metadataFromHeaders(range.headers),
        size: parsedRange?.total ?? this.#metadata?.size ?? null,
        acceptsRanges: true,
      };
      return this.#metadata;
    }
    await range.body?.cancel();

    if (this.#metadata) return this.#metadata;
    throw new RangeUnavailableError(`Unable to inspect remote source (${range.status})`);
  }

  async read(start: number, endExclusive: number, signal?: AbortSignal): Promise<Uint8Array> {
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(endExclusive)) {
      throw new RangeError("Range offsets must be safe integers");
    }
    if (start < 0 || endExclusive <= start) {
      throw new RangeError("Range must satisfy 0 <= start < endExclusive");
    }

    const response = await this.#fetch(this.url, {
      headers: { Range: `bytes=${start}-${endExclusive - 1}` },
      credentials: "omit",
      redirect: "follow",
      signal,
    });

    if (response.status === 206) {
      const range = parseContentRange(response.headers.get("content-range"));
      if (!range || range.start !== start || range.end !== endExclusive - 1) {
        await response.body?.cancel();
        throw new InvalidRangeResponseError("Content-Range does not match the requested bytes");
      }
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.byteLength !== endExclusive - start) {
        throw new InvalidRangeResponseError("Partial response has an unexpected byte length");
      }
      return bytes;
    }

    if (response.status === 200) {
      const declaredSize = parseLength(response.headers.get("content-length"));
      if (declaredSize === null || declaredSize > this.#maxFullDownloadBytes) {
        await response.body?.cancel();
        throw new RangeUnavailableError(
          "The source ignored Range and its full body is not within the download budget",
        );
      }
      const body = new Uint8Array(await response.arrayBuffer());
      if (body.byteLength > this.#maxFullDownloadBytes || endExclusive > body.byteLength) {
        throw new RangeUnavailableError(
          "The bounded full-download fallback cannot satisfy the range",
        );
      }
      return body.slice(start, endExclusive);
    }

    await response.body?.cancel();
    throw new RangeUnavailableError(`Remote range request failed (${response.status})`);
  }
}

interface ParsedContentRange {
  start: number;
  end: number;
  total: number | null;
}

function parseContentRange(value: string | null): ParsedContentRange | null {
  const match = /^bytes (\d+)-(\d+)\/(\d+|\*)$/i.exec(value ?? "");
  if (!match) return null;
  const start = Number(match[1]);
  const end = Number(match[2]);
  const total = match[3] === "*" ? null : Number(match[3]);
  if (![start, end].every(Number.isSafeInteger) || end < start) return null;
  if (total !== null && (!Number.isSafeInteger(total) || total <= end)) return null;
  return { start, end, total };
}

function parseLength(value: string | null): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const size = Number(value);
  return Number.isSafeInteger(size) ? size : null;
}

function metadataFromHeaders(headers: Headers): RemoteObjectMetadata {
  return {
    size: parseLength(headers.get("content-length")),
    mediaType: headers.get("content-type"),
    etag: headers.get("etag"),
    lastModified: headers.get("last-modified"),
    acceptsRanges: headers.get("accept-ranges")?.toLowerCase() === "bytes",
  };
}
