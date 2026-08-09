#!/usr/bin/env node

import { copyFile, mkdir } from "node:fs/promises";
import path from "node:path";

import { type ArtifactKind, Molhub } from "./node.js";

interface Arguments {
  readonly command: "search" | "info" | "fetch";
  readonly value: string | undefined;
  readonly registry: string | undefined;
  readonly kind: ArtifactKind | undefined;
  readonly into: string | undefined;
}

const USAGE = [
  "Usage:",
  "  molhub-js search [query] [--kind dataset|model|plugin] [--registry snapshot.json]",
  "  molhub-js info <coordinate> [--registry snapshot.json]",
  "  molhub-js fetch <coordinate> [--into path] [--registry snapshot.json]",
].join("\n");

try {
  const args = parseArguments(process.argv.slice(2));
  const hub = new Molhub(args.registry ? { registry: args.registry } : {});
  if (args.command === "search") {
    const entries = await hub.search({
      ...(args.value ? { query: args.value } : {}),
      ...(args.kind ? { kind: args.kind } : {}),
    });
    if (entries.length === 0) throw new Error("No artifacts matched.");
    const width = Math.max(...entries.map((entry) => entry.coordinate.length));
    for (const entry of entries) {
      const license = entry.license ? `  ${entry.license}` : "";
      process.stdout.write(`${entry.coordinate.padEnd(width)}  ${entry.title}${license}\n`);
    }
  } else if (args.command === "info") {
    const entry = await hub.resolve(requiredValue(args));
    process.stdout.write(`${entry.coordinate}\n`);
    field("title", entry.title);
    field("about", entry.description);
    field("license", entry.license);
    field("doi", entry.doi);
    field("graph", entry.targets.graph_level.join(", "));
    field("atom", entry.targets.atom_level.join(", "));
    for (const artifact of entry.artifacts) {
      const size = artifact.size ? `  ${artifact.size} B` : "";
      process.stdout.write(`  [${artifact.role}] ${artifact.filename}${size}\n`);
      if (artifact.format) process.stdout.write(`    format: ${artifact.format}\n`);
      if (artifact.media_type) process.stdout.write(`    media-type: ${artifact.media_type}\n`);
      if (artifact.digest) process.stdout.write(`    ${artifact.digest}\n`);
      for (const locator of artifact.locators) process.stdout.write(`    - ${locator}\n`);
    }
  } else {
    const coordinate = requiredValue(args);
    const entry = await hub.resolve(coordinate);
    const files = await hub.fetch(coordinate);
    for (const [role, source] of Object.entries(files)) {
      let destination = source;
      if (args.into) {
        await mkdir(args.into, { recursive: true });
        const artifact = entry.artifacts.find((candidate) => candidate.role === role);
        if (!artifact) throw new Error(`${entry.coordinate} does not declare role ${role}.`);
        destination = path.join(args.into, artifact.filename);
        await copyFile(source, destination);
      }
      process.stdout.write(`${role}\t${destination}\n`);
    }
  }
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n\n${USAGE}\n`);
  process.exitCode = 1;
}

function field(label: string, value: string | null): void {
  if (value) process.stdout.write(`  ${label.padEnd(10)} ${value}\n`);
}

function requiredValue(args: Arguments): string {
  if (!args.value) throw new Error(`${args.command} requires a coordinate.`);
  return args.value;
}

function parseArguments(argv: readonly string[]): Arguments {
  const command = argv[0];
  if (command !== "search" && command !== "info" && command !== "fetch") {
    throw new Error(USAGE);
  }
  let value: string | undefined;
  let registry: string | undefined;
  let kind: ArtifactKind | undefined;
  let into: string | undefined;
  for (let index = 1; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token) continue;
    if (!token.startsWith("--")) {
      if (value) throw new Error(`Unexpected argument ${JSON.stringify(token)}.`);
      value = token;
      continue;
    }
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) throw new Error(`${token} requires a value.`);
    index += 1;
    if (token === "--registry") registry = next;
    else if (token === "--kind" && command === "search") {
      if (next !== "dataset" && next !== "model" && next !== "plugin") {
        throw new Error(`Unknown artifact kind ${JSON.stringify(next)}.`);
      }
      kind = next;
    } else if (token === "--into" && command === "fetch") into = next;
    else throw new Error(`Unknown option ${token} for ${command}.`);
  }
  return { command, value, registry, kind, into };
}
