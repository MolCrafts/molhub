import { UnknownScheme } from "./errors.js";
import { BoundedJsonReader } from "./json-response.js";
import type { Locator } from "./locator.js";

export interface RemoteFile {
  readonly url: string;
  readonly filename: string;
  readonly size?: number;
  readonly upstreamDigest?: string;
}

export interface Source {
  readonly scheme: string;
  resolve(locator: Locator): Promise<readonly RemoteFile[]>;
}

export class Sources {
  readonly #byScheme: ReadonlyMap<string, Source>;

  constructor(sources: readonly Source[]) {
    const byScheme = new Map<string, Source>();
    for (const source of sources) {
      if (byScheme.has(source.scheme)) throw new Error(`Duplicate source scheme ${source.scheme}.`);
      byScheme.set(source.scheme, source);
    }
    this.#byScheme = byScheme;
  }

  static defaults(): Sources {
    return new Sources([
      new DirectSource("https"),
      new DirectSource("http"),
      new FigshareSource(),
      new ZenodoSource(),
      new HuggingFaceSource(),
      new MolhubSource(),
    ]);
  }

  for(locator: Locator): Source {
    const source = this.#byScheme.get(locator.scheme);
    if (!source) throw new UnknownScheme(`No source handles ${locator.scheme}://.`);
    return source;
  }
}

export class DirectSource implements Source {
  constructor(readonly scheme: "http" | "https") {}

  async resolve(locator: Locator): Promise<readonly RemoteFile[]> {
    const url = locator.toString();
    const pathname = new URL(url).pathname;
    return [{ url, filename: pathname.split("/").filter(Boolean).at(-1) ?? "download" }];
  }
}

export class HuggingFaceSource implements Source {
  readonly scheme = "hf";

  constructor(
    private readonly endpoint = "https://huggingface.co",
    private readonly repoType: "datasets" | "models" | "spaces" = "datasets",
  ) {}

  async resolve(locator: Locator): Promise<readonly RemoteFile[]> {
    const [organization, repositoryAndRevision, ...fileParts] = locator.path.split("/");
    if (!organization || !repositoryAndRevision || fileParts.length === 0) {
      throw new Error(`${locator} must be org/repo@revision/path.`);
    }
    const [repository, revision = "main"] = repositoryAndRevision.split("@", 2);
    if (!repository) throw new Error(`${locator} has no repository name.`);
    const prefix = this.repoType === "models" ? "" : `${this.repoType}/`;
    return [
      {
        url: `${this.endpoint.replace(/\/$/, "")}/${prefix}${organization}/${repository}/resolve/${revision}/${fileParts.join("/")}`,
        filename: fileParts.at(-1) ?? "download",
      },
    ];
  }
}

export class MolhubSource implements Source {
  readonly scheme = "molhub";

  constructor(private readonly baseUrl = "https://hub.molcrafts.org") {}

  async resolve(locator: Locator): Promise<readonly RemoteFile[]> {
    return [
      {
        url: `${this.baseUrl.replace(/\/$/, "")}/${locator.path.replace(/^\//, "")}`,
        filename: locator.path.split("/").at(-1) ?? "download",
      },
    ];
  }
}

abstract class JsonApiSource implements Source {
  abstract readonly scheme: string;

  constructor(
    protected readonly apiBase: string,
    protected readonly fetcher = globalThis.fetch,
  ) {}

  abstract resolve(locator: Locator): Promise<readonly RemoteFile[]>;

  protected async json(url: string): Promise<unknown> {
    const response = await this.fetcher(url, {
      headers: { accept: "application/json", "user-agent": "molhub-js/0.1" },
    });
    if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}.`);
    return new BoundedJsonReader(8 * 1024 * 1024).read(response);
  }
}

export class ZenodoSource extends JsonApiSource {
  readonly scheme = "zenodo";

  constructor(apiBase = "https://zenodo.org/api", fetcher = globalThis.fetch) {
    super(apiBase.replace(/\/$/, ""), fetcher);
  }

  async resolve(locator: Locator): Promise<readonly RemoteFile[]> {
    const [recordId, ...wantedParts] = locator.path.split("/");
    const payload = await this.json(`${this.apiBase}/records/${recordId}`);
    const files = objectArray(objectValue(payload, "files"));
    const remotes = files.map((entry) => ({
      url: stringValue(objectValue(objectValue(entry, "links"), "self")),
      filename: stringValue(objectValue(entry, "key")),
      ...optionalNumber("size", objectValue(entry, "size")),
      ...optionalString("upstreamDigest", objectValue(entry, "checksum")),
    }));
    return selectFile(remotes, wantedParts.join("/"), `Zenodo record ${recordId}`);
  }
}

export class FigshareSource extends JsonApiSource {
  readonly scheme = "figshare";

  constructor(apiBase = "https://api.figshare.com/v2", fetcher = globalThis.fetch) {
    super(apiBase.replace(/\/$/, ""), fetcher);
  }

  async resolve(locator: Locator): Promise<readonly RemoteFile[]> {
    const [articleId = "", maybeVersion = "", ...rest] = locator.path.split("/");
    const version = /^v\d+$/.test(maybeVersion) ? maybeVersion.slice(1) : "";
    const wanted = version ? rest.join("/") : [maybeVersion, ...rest].filter(Boolean).join("/");
    const endpoint = version
      ? `${this.apiBase}/articles/${articleId}/versions/${version}`
      : `${this.apiBase}/articles/${articleId}/files`;
    const payload = await this.json(endpoint);
    const files = Array.isArray(payload)
      ? objectArray(payload)
      : objectArray(objectValue(payload, "files"));
    const remotes = files.map((entry) => {
      const digest = objectValue(entry, "supplied_md5") ?? objectValue(entry, "computed_md5");
      return {
        url: stringValue(objectValue(entry, "download_url")),
        filename: stringValue(objectValue(entry, "name")),
        ...optionalNumber("size", objectValue(entry, "size")),
        ...(typeof digest === "string" ? { upstreamDigest: `md5:${digest}` } : {}),
      };
    });
    return selectFile(remotes, wanted, `Figshare article ${articleId}`);
  }
}

function selectFile(
  files: readonly RemoteFile[],
  wanted: string,
  owner: string,
): readonly RemoteFile[] {
  if (files.length === 0) throw new Error(`${owner} lists no files.`);
  if (!wanted) return files;
  const selected = files.filter((file) => file.filename === wanted);
  if (selected.length === 0) throw new Error(`${owner} has no file ${JSON.stringify(wanted)}.`);
  return selected;
}

function objectValue(input: unknown, key: string): unknown {
  return typeof input === "object" && input !== null ? Reflect.get(input, key) : undefined;
}

function objectArray(input: unknown): Record<string, unknown>[] {
  if (!Array.isArray(input)) return [];
  return input.filter(
    (item): item is Record<string, unknown> => typeof item === "object" && item !== null,
  );
}

function stringValue(input: unknown): string {
  if (typeof input !== "string" || !input)
    throw new Error("Remote metadata omitted a required string.");
  return input;
}

function optionalString<Key extends string>(key: Key, input: unknown): { [K in Key]?: string } {
  return typeof input === "string" ? ({ [key]: input } as { [K in Key]: string }) : {};
}

function optionalNumber<Key extends string>(key: Key, input: unknown): { [K in Key]?: number } {
  return typeof input === "number" ? ({ [key]: input } as { [K in Key]: number }) : {};
}
