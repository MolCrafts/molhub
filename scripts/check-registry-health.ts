import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
	Locator,
	type MolhubRegistry,
	type RegistryArtifact,
} from "@molcrafts/molhub/core";
import { Sources } from "@molcrafts/molhub/node";

interface HealthResult {
	coordinate: string;
	role: string;
	locator: string;
	source: string;
	ok: boolean;
	status: number | null;
	message: string;
}

const input = resolve(process.argv[2] ?? "dist/registry.json");
const output = resolve(process.argv[3] ?? "registry-health-report.json");
const registry = JSON.parse(readFileSync(input, "utf8")) as MolhubRegistry;
const sources = Sources.defaults();
const results: HealthResult[] = [];

for (const entry of registry.entries) {
	for (const artifact of entry.artifacts) {
		for (const locatorText of artifact.locators) {
			results.push(await checkLocator(entry.coordinate, artifact, locatorText));
		}
	}
}

const report = {
	checked_at: new Date().toISOString(),
	registry: input,
	totals: {
		locators: results.length,
		healthy: results.filter((result) => result.ok).length,
		failed: results.filter((result) => !result.ok).length,
	},
	results,
};
writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`, "utf8");

const failures = results.filter((result) => !result.ok);
for (const failure of failures) {
	console.error(
		`${failure.source} ${failure.coordinate}#${failure.role} ${failure.locator}: ${failure.message}`,
	);
}
console.log(
	`Registry health: ${report.totals.healthy}/${report.totals.locators} locators healthy; report ${output}`,
);
if (failures.length > 0) process.exitCode = 1;

async function checkLocator(
	coordinate: string,
	artifact: RegistryArtifact,
	locatorText: string,
): Promise<HealthResult> {
	const locator = Locator.parse(locatorText);
	const base = {
		coordinate,
		role: artifact.role,
		locator: locatorText,
		source: locator.scheme,
	};
	try {
		const remotes = await sources.for(locator).resolve(locator);
		if (remotes.length === 0) throw new Error("source resolved no files");
		const remote = remotes[0];
		if (!remote) throw new Error("source resolved no preferred file");
		const response = await metadataRequest(remote.url);
		const observedSize =
			remote.size ??
			contentRangeTotal(response.headers.get("content-range")) ??
			contentLength(response);
		if (
			artifact.size !== null &&
			observedSize !== null &&
			artifact.size !== observedSize
		) {
			throw new Error(
				`size changed: manifest ${artifact.size}, upstream ${observedSize}`,
			);
		}
		if (
			artifact.digest !== null &&
			remote.upstreamDigest !== undefined &&
			artifact.digest.toLowerCase() !== remote.upstreamDigest.toLowerCase()
		) {
			throw new Error(
				`published digest changed: manifest ${artifact.digest}, upstream ${remote.upstreamDigest}`,
			);
		}
		await response.body?.cancel();
		return {
			...base,
			ok: true,
			status: response.status,
			message: remote.upstreamDigest
				? "status, size, and published digest checked"
				: "status and size checked",
		};
	} catch (error) {
		return {
			...base,
			ok: false,
			status: null,
			message:
				error instanceof Error
					? error.message.slice(0, 500)
					: String(error).slice(0, 500),
		};
	}
}

async function metadataRequest(url: string): Promise<Response> {
	let response = await requestWithRetry(url, {
		headers: { Range: "bytes=0-0" },
	});
	if (response.status === 405 || response.status === 501) {
		await response.body?.cancel();
		response = await requestWithRetry(url, { method: "HEAD" });
	}
	if (!response.ok) {
		await response.body?.cancel();
		throw new Error(`metadata request returned HTTP ${response.status}`);
	}
	return response;
}

async function requestWithRetry(
	url: string,
	init: RequestInit,
): Promise<Response> {
	let lastError: unknown;
	for (let attempt = 0; attempt < 3; attempt += 1) {
		try {
			const response = await fetch(url, {
				...init,
				redirect: "follow",
				signal: AbortSignal.timeout(20_000),
				headers: {
					...init.headers,
					"accept-encoding": "identity",
					"user-agent": "molhub-registry-health/0.1",
				},
			});
			if (response.status !== 429 && response.status < 500) return response;
			lastError = new Error(`HTTP ${response.status}`);
			await response.body?.cancel();
		} catch (error) {
			lastError = error;
		}
		if (attempt < 2)
			await new Promise((resolveDelay) =>
				setTimeout(resolveDelay, 500 * 2 ** attempt),
			);
	}
	throw lastError instanceof Error
		? lastError
		: new Error("metadata request failed");
}

function contentLength(response: Response): number | null {
	const value = response.headers.get("content-length");
	return value && /^\d+$/.test(value) ? Number(value) : null;
}

function contentRangeTotal(value: string | null): number | null {
	const match = /\/([0-9]+)$/.exec(value ?? "");
	return match?.[1] ? Number(match[1]) : null;
}
