import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

const clientRoot = join(import.meta.dirname, "../dist/client");
const initialPages = ["index.html", "explore/index.html", "a/dataset/molcrafts/3bpa/v1/index.html"];
const forbidden = ["molvis:ready", "ScatterChart", "vegaEmbed", "@babylonjs"];

for (const htmlPath of walk(clientRoot).filter((path) => path.endsWith(".html"))) {
  if (!readFileSync(htmlPath, "utf8").trimEnd().endsWith("</html>")) {
    throw new Error(`Prerendered HTML has a corrupt suffix: ${relative(clientRoot, htmlPath)}`);
  }
}

for (const page of initialPages) {
  const htmlPath = join(clientRoot, page);
  if (!existsSync(htmlPath)) throw new Error(`Missing prerendered bundle-check page: ${page}`);
  const html = readFileSync(htmlPath, "utf8");
  const initialScripts = new Set(
    [...html.matchAll(/(?:href|src)="\/molhub\/(assets\/js\/[^"]+\.js)"/g)].map(
      (match) => match[1] as string,
    ),
  );
  for (const script of initialScripts) {
    const source = readFileSync(join(clientRoot, script), "utf8");
    for (const marker of forbidden) {
      if (source.includes(marker)) {
        throw new Error(`${page} initially loads Inspector marker ${marker} from ${script}`);
      }
    }
  }
}

const allJavaScript = walk(join(clientRoot, "assets/js")).filter((path) => path.endsWith(".js"));
const inspectorSurface = allJavaScript.filter((path) => {
  const source = readFileSync(path, "utf8");
  return source.includes("molvis:ready") || source.includes("ScatterChart");
});

if (inspectorSurface.length === 0) {
  throw new Error("Inspector dependencies are missing from the async chunk graph");
}

console.log(
  `Bundle isolation passed; Inspector surface is async in ${inspectorSurface
    .map((path) => relative(clientRoot, path))
    .join(", ")}.`,
);

function walk(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}
