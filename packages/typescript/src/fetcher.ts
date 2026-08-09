import { createHash } from "node:crypto";
import { open } from "node:fs/promises";

import { Digest } from "./digest.js";
import { AllLocatorsFailed, BadStatus, DigestMismatch } from "./errors.js";
import { FileStore } from "./file-store.js";
import { Locator } from "./locator.js";
import { Sources } from "./source.js";

export interface FetcherOptions {
  readonly sources?: Sources;
  readonly store?: FileStore;
  readonly fetch?: typeof globalThis.fetch;
}

export class Fetcher {
  readonly sources: Sources;
  readonly store: FileStore;
  readonly #fetch: typeof globalThis.fetch;

  constructor(options: FetcherOptions = {}) {
    this.sources = options.sources ?? Sources.defaults();
    this.store = options.store ?? new FileStore();
    this.#fetch = options.fetch ?? globalThis.fetch;
  }

  async fetch(
    locators: readonly string[],
    key: string,
    expectedDigest?: string | null,
  ): Promise<string> {
    if (await this.store.has(key)) return this.store.pathFor(key);
    const expected = expectedDigest ? Digest.parse(expectedDigest) : undefined;
    const reasons: Array<readonly [string, Error]> = [];

    for (const text of locators) {
      try {
        const locator = Locator.parse(text);
        const remotes = await this.sources.for(locator).resolve(locator);
        const remote = remotes[0];
        if (!remote) throw new Error(`${locator} resolved to no files.`);
        return await this.transfer(remote.url, key, expected);
      } catch (error) {
        reasons.push([text, error instanceof Error ? error : new Error(String(error))]);
      }
    }
    throw new AllLocatorsFailed(reasons);
  }

  private async transfer(url: string, key: string, expected?: Digest): Promise<string> {
    const partial = this.store.tempPath(key);
    await this.store.ensureTempParent(partial);
    const hash = expected ? createHash(expected.algorithm) : undefined;
    const handle = await open(partial, "wx");
    try {
      const response = await this.#fetch(url, { headers: { "user-agent": "molhub-js/0.1" } });
      if (response.status !== 200)
        throw new BadStatus(`${url} returned HTTP ${response.status}, expected 200.`);
      if (!response.body) throw new Error(`${url} returned no response body.`);
      const reader = response.body.getReader();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        await handle.write(value);
        hash?.update(value);
      }
      await handle.sync();
      if (expected && hash) {
        const actual = new Digest(expected.algorithm, hash.digest("hex"));
        if (!actual.matches(expected)) {
          throw new DigestMismatch(`${url} returned ${actual}, expected ${expected}.`);
        }
      }
      await handle.close();
      return await this.store.put(partial, key);
    } catch (error) {
      await handle.close().catch(() => undefined);
      throw error;
    } finally {
      await this.store.discard(partial);
    }
  }
}
