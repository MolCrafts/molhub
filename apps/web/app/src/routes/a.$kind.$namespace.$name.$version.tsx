import { Link, createFileRoute, notFound } from "@tanstack/react-router";
import {
  ArrowLeft,
  ArrowUpRight,
  CheckCircle2,
  FileArchive,
  Files,
  Fingerprint,
  Globe2,
  HardDrive,
  ScanSearch,
} from "lucide-react";
import type { ReactNode } from "react";

import { KindBadge } from "@/components/kind-badge";
import { SignalBadge } from "@/components/signal-badge";
import { CopyButton, UsagePanel } from "@/components/snippets";
import { TargetChips } from "@/components/target-chips";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Code } from "@/components/ui/code";
import { formatBytes } from "@/lib/bytes";
import { EntryFacts } from "@/lib/entry-facts";
import { inspectability } from "@/lib/inspectability";
import { REGISTRY } from "@/lib/registry";
import type { RegistryArtifact, RegistryEntry } from "@/types/registry";

export const Route = createFileRoute("/a/$kind/$namespace/$name/$version")({
  loader: ({ params }) => {
    const coordinate = `${params.kind}:${params.namespace}/${params.name}@${params.version}`;
    const entry = REGISTRY.entry(coordinate);
    if (!entry) throw notFound();
    return entry;
  },
  head: ({ loaderData }) => ({
    meta: loaderData
      ? [
          { title: `${loaderData.title} — MolHub` },
          {
            name: "description",
            content:
              loaderData.description ??
              `Resolve ${loaderData.coordinate} and inspect its published files.`,
          },
        ]
      : [],
  }),
  component: ArtifactDetailPage,
});

function ArtifactDetailPage() {
  const entry = Route.useLoaderData();
  const facts = new EntryFacts(entry);
  const size = formatBytes(facts.size.bytes);
  const sourcePlatforms = new Set(
    entry.artifacts.flatMap((artifact) => artifact.locators.map(locatorLabel)),
  );
  const inspectable = entry.artifacts.filter(
    (artifact) => inspectability(artifact).state === "direct",
  );
  const canonicalInspectRole =
    inspectable.find((artifact) => artifact.role === "train_300K")?.role ?? inspectable[0]?.role;

  return (
    <>
      <section className="border-border border-b bg-canvas-tinted">
        <div className="page-shell py-7 sm:py-9">
          <Button asChild variant="ghost" size="sm" className="-ml-2">
            <Link to="/explore" search={{}}>
              <ArrowLeft aria-hidden="true" /> Back to registry
            </Link>
          </Button>

          <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-end">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <KindBadge kind={entry.kind} />
                <Badge variant="outline" className="font-mono">
                  @{entry.version}
                </Badge>
              </div>
              <h1 className="display-balance mt-4 max-w-4xl font-display font-bold text-3xl tracking-tight sm:text-4xl">
                {entry.title}
              </h1>
              <p className="text-pretty mt-3 max-w-3xl text-muted-foreground">
                {entry.description ?? "No description has been recorded for this artifact."}
              </p>

              <div className="mt-5 flex max-w-3xl flex-col gap-2 rounded-control border border-accent-line bg-accent-soft p-3 sm:flex-row sm:items-center">
                <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono font-medium text-accent-ink text-sm">
                  {entry.coordinate}
                </code>
                <CopyButton text={entry.coordinate} subject="the artifact coordinate" />
              </div>
            </div>

            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-panel border border-border bg-border lg:grid-cols-1">
              <Metric icon={<Files />} value={`${facts.fileCount}`} label="published files" />
              <Metric
                icon={<HardDrive />}
                value={size ? `${facts.size.complete ? "" : "≥ "}${size}` : "Unknown"}
                label="aggregate size"
              />
              <Metric
                icon={<Globe2 />}
                value={`${sourcePlatforms.size}`}
                label="source platforms"
              />
            </dl>
          </div>
        </div>
      </section>

      <div className="page-shell grid gap-8 py-8 lg:grid-cols-[minmax(0,1fr)_19rem] lg:py-10">
        <div className="min-w-0 space-y-10">
          <UsagePanel entry={entry} />

          <section aria-labelledby="published-files">
            <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <h2 id="published-files" className="font-display font-bold text-2xl tracking-tight">
                Files
              </h2>
              <p className="text-muted-foreground text-xs">Sources follow manifest order.</p>
            </div>
            <div className="mt-4 grid gap-3">
              {entry.artifacts.map((artifact) => (
                <ArtifactFile
                  key={`${artifact.role}:${artifact.filename}`}
                  artifact={artifact}
                  entry={entry}
                  canonicalInspect={artifact.role === canonicalInspectRole}
                />
              ))}
            </div>
          </section>
        </div>

        <aside
          className="space-y-4 lg:sticky lg:top-24 lg:self-start"
          aria-label="Artifact metadata"
        >
          <MetadataCard entry={entry} facts={facts} />
        </aside>
      </div>
    </>
  );
}

function Metric({ icon, value, label }: { icon: ReactNode; value: string; label: string }) {
  return (
    <div className="bg-surface p-4">
      <dt className="flex items-center gap-2 text-subtle-foreground text-xs">
        <span className="[&_svg]:size-3.5">{icon}</span>
        {label}
      </dt>
      <dd className="mt-1 font-display font-semibold text-xl tracking-tight">{value}</dd>
    </div>
  );
}

function ArtifactFile({
  artifact,
  entry,
  canonicalInspect,
}: {
  artifact: RegistryArtifact;
  entry: RegistryEntry;
  canonicalInspect: boolean;
}) {
  const size = formatBytes(artifact.size);
  const capability = inspectability(artifact);
  return (
    <article className="overflow-hidden rounded-panel border border-border bg-surface">
      <div className="flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <FileArchive className="size-4 text-accent-ink" aria-hidden="true" />
            <h3 className="break-all font-mono font-semibold text-sm">{artifact.filename}</h3>
            <Badge variant="soft">{artifact.role}</Badge>
          </div>
          <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-muted-foreground text-xs">
            <span>{size ?? "size unknown"}</span>
            <span>
              {artifact.locators.length} source{artifact.locators.length === 1 ? "" : "s"}
            </span>
            <span>{artifact.digest ? "published digest" : "byte-count verification"}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {capability.state === "direct" ? (
            <Button asChild size="sm">
              <Link
                to="/inspect/$kind/$namespace/$name/$version"
                params={{
                  kind: entry.kind,
                  namespace: entry.namespace,
                  name: entry.name,
                  version: entry.version,
                }}
                search={
                  canonicalInspect
                    ? {}
                    : {
                        role: artifact.role,
                        frame: 0,
                        x: "frame",
                        y: "energy",
                        color: "none",
                      }
                }
              >
                <ScanSearch aria-hidden="true" /> Inspect
              </Link>
            </Button>
          ) : null}
          {artifact.locators[0] ? (
            <Button asChild variant="outline" size="sm">
              <a href={locatorHref(artifact.locators[0])} target="_blank" rel="noreferrer">
                View upstream <ArrowUpRight aria-hidden="true" />
              </a>
            </Button>
          ) : null}
        </div>
      </div>

      <div className="border-border border-t bg-canvas-tinted p-4">
        <ol className="space-y-2">
          {artifact.locators.map((locator, index) => (
            <li
              key={locator}
              className="grid gap-1 sm:grid-cols-[4.5rem_minmax(0,1fr)] sm:items-start"
            >
              <span className="font-medium text-subtle-foreground text-xs">
                {index === 0 ? "preferred" : `mirror ${index}`}
              </span>
              <a
                href={locatorHref(locator)}
                target="_blank"
                rel="noreferrer"
                className="min-w-0 break-all font-mono text-accent-ink text-xs hover:underline"
              >
                {locator}
              </a>
            </li>
          ))}
        </ol>
        {artifact.digest ? (
          <div className="mt-3 grid gap-1 sm:grid-cols-[4.5rem_minmax(0,1fr)]">
            <span className="flex items-center gap-1 font-medium text-subtle-foreground text-xs">
              <Fingerprint className="size-3" aria-hidden="true" /> digest
            </span>
            <Code wrap="anywhere" className="text-xs">
              {artifact.digest}
            </Code>
          </div>
        ) : null}
      </div>
    </article>
  );
}

function MetadataCard({ entry, facts }: { entry: RegistryEntry; facts: EntryFacts }) {
  return (
    <section className="rounded-panel border border-border bg-surface p-4">
      <div className="flex items-center gap-2">
        <CheckCircle2 className="size-5 text-accent-ink" aria-hidden="true" />
        <h2 className="font-display font-semibold text-lg">Manifest facts</h2>
      </div>

      <dl className="mt-5 space-y-4 text-sm">
        <MetaRow label="Namespace">
          <Code>{entry.namespace}</Code>
        </MetaRow>
        <MetaRow label="License">
          <SignalBadge signal={facts.licence} />
        </MetaRow>
        <MetaRow label="Integrity">
          <SignalBadge signal={facts.integrity} />
        </MetaRow>
        <MetaRow label="Availability">
          <SignalBadge signal={facts.sources} />
        </MetaRow>
        {entry.doi ? (
          <MetaRow label="DOI">
            <a
              href={`https://doi.org/${entry.doi}`}
              target="_blank"
              rel="noreferrer"
              className="break-all font-mono text-accent-ink text-xs hover:underline"
            >
              {entry.doi}
            </a>
          </MetaRow>
        ) : null}
        <MetaRow label="Targets">
          <TargetChips targets={facts.targets} />
        </MetaRow>
      </dl>
    </section>
  );
}

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-subtle-foreground text-xs">{label}</dt>
      <dd className="mt-1">{children}</dd>
    </div>
  );
}

function locatorLabel(locator: string): string {
  const [scheme = "source"] = locator.split(":", 1);
  if (scheme !== "http" && scheme !== "https") return scheme;
  try {
    return new URL(locator).hostname.replace(/^www\./, "");
  } catch {
    return scheme;
  }
}

function locatorHref(locator: string): string {
  const separator = locator.indexOf("://");
  const scheme = separator === -1 ? "https" : locator.slice(0, separator);
  const path = separator === -1 ? locator : locator.slice(separator + 3);
  if (scheme === "figshare")
    return `https://figshare.com/articles/dataset/_/${path.split("/", 1)[0]}`;
  if (scheme === "zenodo") return `https://zenodo.org/records/${path.split("/", 1)[0]}`;
  return locator;
}
