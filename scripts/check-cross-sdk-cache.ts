import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Fetcher, FileStore } from "@molcrafts/molhub/node";

const root = await mkdtemp(join(tmpdir(), "molhub-cross-sdk-cache-"));
const pythonKey = "dataset/molcrafts/cross-sdk@v1/python";
const nodeKey = "dataset/molcrafts/cross-sdk@v1/node";

try {
	runPython(
		`
from pathlib import Path
import sys
from molhub.sources import BlobStore
root, key = sys.argv[1:]
source = Path(root) / "python-source"
source.write_bytes(b"written-by-python")
BlobStore(root).put(source, key)
`,
		root,
		pythonKey,
	);

	const store = new FileStore(root);
	const fetcher = new Fetcher({
		store,
		fetch: async () => {
			throw new Error("Node attempted network for a Python cache entry");
		},
	});
	const pythonPath = await fetcher.fetch(
		["https://must-not-run.invalid/python"],
		pythonKey,
	);
	if ((await readFile(pythonPath, "utf8")) !== "written-by-python") {
		throw new Error("Node read different bytes from the Python cache entry.");
	}

	const nodeSource = join(root, "node-source");
	await writeFile(nodeSource, "written-by-node", "utf8");
	await store.put(nodeSource, nodeKey);
	runPython(
		`
from pathlib import Path
import sys
from molhub.sources import BlobStore, Fetcher
root, key = sys.argv[1:]
path = Fetcher(blobs=BlobStore(root)).fetch(["https://must-not-run.invalid/node"], key)
if path.read_bytes() != b"written-by-node":
    raise SystemExit("Python read different bytes from the Node cache entry")
`,
		root,
		nodeKey,
	);

	console.log(
		"Python and Node share cache entries in both directions without network access.",
	);
} finally {
	await rm(root, { recursive: true, force: true });
}

function runPython(source: string, ...args: string[]) {
	const result = spawnSync("uv", ["run", "python", "-c", source, ...args], {
		cwd: join(import.meta.dirname, ".."),
		encoding: "utf8",
	});
	if (result.status !== 0) {
		throw new Error(
			`Python cache probe failed:\n${result.stderr || result.stdout}`,
		);
	}
}
