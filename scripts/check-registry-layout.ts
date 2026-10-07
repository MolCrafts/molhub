import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

const registryRoot = resolve(process.argv[2] ?? "../molhub-registry");
const repositoryFiles = execFileSync(
	"git",
	[
		"-C",
		registryRoot,
		"ls-files",
		"-z",
		"--cached",
		"--others",
		"--exclude-standard",
	],
	{ encoding: "utf8" },
)
	.split("\0")
	.filter(Boolean);

const exactFiles = new Set([
	".gitignore",
	".github/CODEOWNERS",
	"CLAUDE.md",
	"LICENSE",
	"LICENSE.md",
	"README.md",
]);
const allowedPatterns = [
	/^\.github\/workflows\/[^/]+\.ya?ml$/,
	/^\.github\/actions\/[^/]+\/action\.ya?ml$/,
	/^artifacts\/(dataset|model|plugin)\/[^/]+\/[^/]+\/[^/]+\.yaml$/,
];

const unexpected = repositoryFiles.filter(
	(path) =>
		!exactFiles.has(path) &&
		!allowedPatterns.some((pattern) => pattern.test(path)),
);
if (unexpected.length > 0) {
	throw new Error(
		`molhub-registry contains tracked files outside the data-only allowlist:\n${unexpected
			.map((path) => `- ${path}`)
			.join("\n")}`,
	);
}

const manifests = repositoryFiles.filter((path) =>
	path.startsWith("artifacts/"),
);
if (manifests.length === 0)
	throw new Error("molhub-registry tracks no artifact manifests.");
console.log(
	`Registry layout is data-only: ${manifests.length} manifests and ${repositoryFiles.length - manifests.length} governance files.`,
);
