import { execFileSync } from "node:child_process";
import {
	mkdtempSync,
	readFileSync,
	readdirSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { join, relative } from "node:path";

const root = join(import.meta.dirname, "..");
const docs = join(root, "docs");
const fence = /```ts\s*\n([\s\S]*?)```/g;
const annotated = /<!--\s*test:\s*([^>]+?)\s*-->\s*```ts\s*\n([\s\S]*?)```/g;
const work = mkdtempSync(join(root, ".docs-ts-"));
let typechecked = 0;
let executed = 0;
let skipped = 0;

try {
	for (const path of markdownFiles(docs)) {
		const source = readFileSync(path, "utf8");
		const all = [...source.matchAll(fence)];
		const examples = [...source.matchAll(annotated)];
		if (all.length !== examples.length) {
			throw new Error(
				`${relative(root, path)} has an unclassified TypeScript fence; add a docs test directive`,
			);
		}
		for (const [index, match] of examples.entries()) {
			const directive = match[1]?.trim() ?? "";
			const code = match[2] ?? "";
			if (directive.startsWith("skip")) {
				skipped += 1;
				console.log(`SKIP ${relative(root, path)}:${index + 1} (${directive})`);
				continue;
			}
			const snippet = join(work, `snippet-${typechecked + 1}.ts`);
			writeFileSync(snippet, code, "utf8");
			execFileSync(
				join(root, "node_modules/.bin/tsc"),
				[
					"--noEmit",
					"--skipLibCheck",
					"--target",
					"ES2022",
					"--module",
					"ESNext",
					"--moduleResolution",
					"bundler",
					snippet,
				],
				{ cwd: root, stdio: "inherit" },
			);
			typechecked += 1;
			if (directive === "exec=node") {
				execFileSync(join(root, "node_modules/.bin/tsx"), [snippet], {
					cwd: root,
					stdio: "inherit",
				});
				executed += 1;
			} else if (directive !== "typecheck") {
				throw new Error(
					`Unknown docs test directive ${JSON.stringify(directive)}`,
				);
			}
		}
	}
} finally {
	rmSync(work, { recursive: true, force: true });
}

if (typechecked === 0)
	throw new Error("No TypeScript documentation examples were found");
console.log(
	`docs TypeScript: ${typechecked} typechecked, ${executed} executed, ${skipped} skipped`,
);

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
