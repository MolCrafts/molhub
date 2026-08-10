import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";

const root = join(import.meta.dirname, "..");
const docs = join(root, "docs");
const forbidden: Array<[RegExp, string]> = [
	[
		/mandatory\s+(?:self[- ]computed\s+)?sha-?256/i,
		"mandatory self-computed SHA-256",
	],
	[
		/must\s+(?:self[- ]compute|calculate)\s+(?:a\s+)?sha-?256/i,
		"self-computed SHA-256",
	],
	[/molhub-(?:js|app)\s+(?:repository|repo)/i, "retired split repository"],
	[/website\s+(?:cannot|can't)\s+submit/i, "website cannot submit"],
	[/\$MOLHUB_HOME\/blobs/i, "retired content-addressed cache layout"],
	[/registry\s+index\s+repository/i, "retired registry index terminology"],
];

for (const path of markdownFiles(docs)) {
	const source = readFileSync(path, "utf8");
	for (const [pattern, label] of forbidden) {
		if (pattern.test(source))
			throw new Error(`${relative(root, path)} contains ${label}`);
	}
}

console.log("Documentation architecture scan passed.");

function markdownFiles(directory: string): string[] {
	return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
		const path = join(directory, entry.name);
		return entry.isDirectory()
			? markdownFiles(path)
			: path.endsWith(".md")
				? [path]
				: [];
	});
}
