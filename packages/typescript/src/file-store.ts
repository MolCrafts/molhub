import { access, mkdir, rename, stat, unlink } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const UNSAFE = /[^A-Za-z0-9._@-]+/g;

export class FileStore {
  readonly root: string;

  constructor(root = process.env.MOLHUB_HOME ?? path.join(os.homedir(), ".cache", "molhub")) {
    this.root = path.resolve(root);
  }

  pathFor(key: string): string {
    return path.join(this.root, "files", ...FileStore.segments(key));
  }

  tempPath(key: string): string {
    return path.join(
      this.root,
      "tmp",
      `${FileStore.segments(key).join("_")}.${crypto.randomUUID()}.part`,
    );
  }

  async has(key: string): Promise<boolean> {
    try {
      return (await stat(this.pathFor(key))).size > 0;
    } catch {
      return false;
    }
  }

  async put(source: string, key: string): Promise<string> {
    const target = this.pathFor(key);
    await mkdir(path.dirname(target), { recursive: true });
    await rename(source, target);
    return target;
  }

  async discard(file: string): Promise<void> {
    try {
      await unlink(file);
    } catch (error) {
      if (typeof error !== "object" || error === null || Reflect.get(error, "code") !== "ENOENT")
        throw error;
    }
  }

  async ensureTempParent(file: string): Promise<void> {
    await mkdir(path.dirname(file), { recursive: true });
  }

  async exists(file: string): Promise<boolean> {
    try {
      await access(file);
      return true;
    } catch {
      return false;
    }
  }

  private static segments(key: string): string[] {
    const segments = key
      .split("/")
      .filter((segment) => segment !== "" && segment !== "." && segment !== "..")
      .map((segment) => segment.replace(UNSAFE, "_"));
    if (segments.length === 0)
      throw new Error(`Cache key ${JSON.stringify(key)} has no usable segments.`);
    return segments;
  }
}
