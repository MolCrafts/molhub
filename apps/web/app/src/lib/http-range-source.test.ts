import { describe, expect, it, rs } from "@rstest/core";

import {
  HttpRangeSource,
  InvalidRangeResponseError,
  RangeUnavailableError,
} from "@/lib/http-range-source";

describe("HttpRangeSource", () => {
  it("reads only the requested bytes from a compliant range server", async () => {
    const fetchMock = rs.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(new Headers(init?.headers).get("range")).toBe("bytes=10-13");
      return new Response(new Uint8Array([10, 11, 12, 13]), {
        status: 206,
        headers: { "content-range": "bytes 10-13/100", etag: '"source-v1"' },
      });
    });
    const source = new HttpRangeSource("https://example.test/record", {
      fetch: fetchMock as typeof fetch,
    });

    await expect(source.read(10, 14)).resolves.toEqual(new Uint8Array([10, 11, 12, 13]));
  });

  it("does not materialize a large response when a server ignores Range", async () => {
    const response = new Response(new Uint8Array([1]), {
      headers: { "content-length": String(100 * 1024 * 1024) },
    });
    const arrayBuffer = rs.spyOn(response, "arrayBuffer");
    const source = new HttpRangeSource("https://example.test/large", {
      fetch: rs.fn(async () => response) as typeof fetch,
      maxFullDownloadBytes: 1024,
    });

    await expect(source.read(0, 1)).rejects.toBeInstanceOf(RangeUnavailableError);
    expect(arrayBuffer).not.toHaveBeenCalled();
  });

  it("allows a proven-small full-download fallback", async () => {
    const bytes = new Uint8Array([0, 1, 2, 3, 4]);
    const source = new HttpRangeSource("https://example.test/small", {
      fetch: rs.fn(
        async () =>
          new Response(bytes, { status: 200, headers: { "content-length": String(bytes.length) } }),
      ) as typeof fetch,
      maxFullDownloadBytes: 10,
    });

    await expect(source.read(1, 4)).resolves.toEqual(new Uint8Array([1, 2, 3]));
  });

  it("rejects corrupt partial responses", async () => {
    const source = new HttpRangeSource("https://example.test/corrupt", {
      fetch: rs.fn(
        async () =>
          new Response(new Uint8Array([1, 2]), {
            status: 206,
            headers: { "content-range": "bytes 2-3/10" },
          }),
      ) as typeof fetch,
    });

    await expect(source.read(0, 2)).rejects.toBeInstanceOf(InvalidRangeResponseError);
  });

  it("passes AbortSignal to the transport", async () => {
    const controller = new AbortController();
    const fetchMock = rs.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      expect(init?.signal).toBe(controller.signal);
      throw new DOMException("Aborted", "AbortError");
    });
    const source = new HttpRangeSource("https://example.test/record", {
      fetch: fetchMock as typeof fetch,
    });

    controller.abort();
    await expect(source.read(0, 1, controller.signal)).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});
