import type { RegistryEntry } from "@/types/registry";
import { type Snippet, demonstrationRole, quote } from "./snippet";

export function typescriptSnippet(entry: RegistryEntry): Snippet {
  const coordinate = quote(entry.coordinate);
  const role = demonstrationRole(entry);
  const lines = [
    'import { Molhub } from "@molcrafts/molhub/node";',
    "",
    "const hub = new Molhub();",
    `const manifest = await hub.resolve(${coordinate});`,
    "console.log(manifest.title, manifest.license, manifest.doi);",
    "",
  ];

  if (role !== null && entry.artifacts.length > 1) {
    lines.push(`const paths = await hub.fetch(${coordinate}, { roles: [${quote(role)}] });`);
    lines.push(`console.log(paths[${quote(role)}]);`);
  } else {
    lines.push(`const paths = await hub.fetch(${coordinate});`);
    lines.push("console.log(paths);");
  }

  return {
    language: "typescript",
    label: "TypeScript",
    caption: "npm install @molcrafts/molhub",
    code: lines.join("\n"),
    commentPrefix: "//",
    availability: "runnable",
  };
}
