import { Link, createFileRoute, notFound } from "@tanstack/react-router";
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  Copy,
  Download,
  Pause,
  Play,
  TriangleAlert,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { MolvisPanel, type TrajectoryMetadata } from "@/components/inspector/molvis-panel";
import { PropertyPlot } from "@/components/inspector/property-plot";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatBytes } from "@/lib/bytes";
import { inspectability } from "@/lib/inspectability";
import { boundedFrame, inspectorSearchSchema } from "@/lib/inspector-state";
import { REGISTRY } from "@/lib/registry";
import type { RegistryArtifact } from "@/types/registry";

export const Route = createFileRoute("/inspect/$kind/$namespace/$name/$version")({
  validateSearch: inspectorSearchSchema,
  loader: ({ params }) => {
    const coordinate = `${params.kind}:${params.namespace}/${params.name}@${params.version}`;
    const entry = REGISTRY.entry(coordinate);
    if (!entry) throw notFound();
    return entry;
  },
  head: ({ loaderData }) => ({
    meta: loaderData
      ? [
          { title: `Inspect ${loaderData.title} — MolHub` },
          {
            name: "description",
            content: `Explore structures and frame properties from ${loaderData.coordinate}.`,
          },
        ]
      : [],
  }),
  component: InspectorPage,
});

function InspectorPage() {
  const entry = Route.useLoaderData();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const [metadata, setMetadata] = useState<TrajectoryMetadata>({
    frameCount: 0,
    labels: new Map(),
    selectedAtoms: 0,
    omittedFields: [],
  });
  const [playing, setPlaying] = useState(false);
  const [copied, setCopied] = useState(false);

  const roles = useMemo(
    () =>
      entry.artifacts
        .map((artifact) => ({ artifact, capability: inspectability(artifact) }))
        .filter(
          (
            value,
          ): value is {
            artifact: RegistryArtifact;
            capability: Extract<ReturnType<typeof inspectability>, { state: "direct" }>;
          } => value.capability.state === "direct",
        ),
    [entry.artifacts],
  );

  const selected =
    roles.find(({ artifact }) => artifact.role === search.role) ??
    roles.find(({ artifact }) => artifact.role === "train_300K") ??
    roles[0];

  const setFrame = useCallback(
    (nextFrame: number) => {
      navigate({
        search: (previous) => ({ ...previous, frame: Math.max(0, Math.trunc(nextFrame)) }),
        replace: true,
      });
    },
    [navigate],
  );

  useEffect(() => {
    if (metadata.frameCount > 0 && search.frame >= metadata.frameCount) {
      setFrame(boundedFrame(search.frame, metadata.frameCount));
    }
  }, [metadata.frameCount, search.frame, setFrame]);

  useEffect(() => {
    if (!playing || metadata.frameCount < 2) return;
    const timer = window.setInterval(() => {
      navigate({
        search: (previous) => ({
          ...previous,
          frame: (previous.frame + 1) % metadata.frameCount,
        }),
        replace: true,
      });
    }, 450);
    return () => window.clearInterval(timer);
  }, [metadata.frameCount, navigate, playing]);

  if (!selected) return <NoInspectableRole entry={entry} />;

  const { artifact, capability } = selected;
  const frame = boundedFrame(search.frame, metadata.frameCount || Number.MAX_SAFE_INTEGER);
  const energy =
    metadata.labels.get("energy") ??
    [...metadata.labels.entries()].find(([name]) => name.toLowerCase() === "energy")?.[1] ??
    null;

  const updateRole = (role: string) => {
    setMetadata({ frameCount: 0, labels: new Map(), selectedAtoms: 0, omittedFields: [] });
    setPlaying(false);
    navigate({
      search: (previous) => ({ ...previous, role, frame: 0 }),
      replace: false,
    });
  };

  const copyLink = async () => {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_500);
  };

  return (
    <div className="pb-10">
      <header className="border-border border-b bg-canvas-tinted">
        <div className="page-shell py-5">
          <Button asChild variant="ghost" size="sm" className="-ml-2">
            <Link
              to="/a/$kind/$namespace/$name/$version"
              params={{
                kind: entry.kind,
                namespace: entry.namespace,
                name: entry.name,
                version: entry.version,
              }}
            >
              <ArrowLeft aria-hidden="true" /> Artifact detail
            </Link>
          </Button>
          <div className="mt-3 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="soft">Inspector</Badge>
                <code className="break-all font-mono text-accent-ink text-xs">
                  {entry.coordinate}
                </code>
              </div>
              <h1 className="mt-2 font-display font-bold text-2xl tracking-tight sm:text-3xl">
                {entry.title}
              </h1>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={copyLink}>
                {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                {copied ? "Copied" : "Copy link"}
              </Button>
              <Button asChild variant="outline" size="sm">
                <a href={capability.source} download={artifact.filename}>
                  <Download aria-hidden="true" /> Download source
                </a>
              </Button>
            </div>
          </div>
        </div>
      </header>

      <main className="page-shell py-6">
        <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(20rem,0.88fr)_minmax(32rem,1.35fr)] lg:items-start">
          <div className="min-w-0 lg:col-start-2 lg:row-start-1">
            <MolvisPanel
              key={artifact.role}
              source={capability.source}
              size={artifact.size}
              format={capability.format}
              frame={frame}
              onFrameChange={setFrame}
              onMetadata={setMetadata}
            />
          </div>

          <section
            className="min-w-0 space-y-4 lg:col-start-1 lg:row-start-1"
            aria-label="Trajectory and properties"
          >
            <div className="rounded-panel border border-border bg-surface p-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block">
                  <span className="font-medium text-xs">Artifact role</span>
                  <select
                    value={artifact.role}
                    onChange={(event) => updateRole(event.target.value)}
                    className="mt-1 h-control w-full rounded-control border border-border-strong bg-surface px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                  >
                    {roles.map(({ artifact: roleArtifact }) => (
                      <option key={roleArtifact.role} value={roleArtifact.role}>
                        {roleArtifact.role}
                      </option>
                    ))}
                  </select>
                </label>
                <div>
                  <p className="font-medium text-xs">Source</p>
                  <a
                    href={capability.source}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 flex min-w-0 items-center gap-1 break-all font-mono text-accent-ink text-xs hover:underline"
                  >
                    {new URL(capability.source).hostname}{" "}
                    <ArrowUpRight aria-hidden="true" className="size-3" />
                  </a>
                  <p className="mt-1 text-muted-foreground text-xs">
                    {artifact.format} · {formatBytes(artifact.size) ?? "size unknown"} · source
                    bytes
                  </p>
                  {metadata.omittedFields.length > 0 ? (
                    <p className="mt-1 text-subtle-foreground text-xs">
                      Viewer omits unsupported metadata ({metadata.omittedFields.join(", ")}); the
                      source and download stay unchanged.
                    </p>
                  ) : null}
                </div>
              </div>

              <div className="mt-4 border-border border-t pt-4">
                <div className="flex items-center gap-3">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    aria-label={playing ? "Pause trajectory" : "Play trajectory"}
                    onClick={() => setPlaying((value) => !value)}
                    disabled={metadata.frameCount < 2}
                  >
                    {playing ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}
                  </Button>
                  <label className="min-w-0 flex-1">
                    <span className="sr-only">Trajectory frame</span>
                    <input
                      type="range"
                      min={0}
                      max={Math.max(0, metadata.frameCount - 1)}
                      value={frame}
                      disabled={metadata.frameCount < 2}
                      onChange={(event) => setFrame(Number(event.target.value))}
                      className="w-full accent-accent"
                    />
                  </label>
                  <output className="min-w-20 text-right font-mono text-xs">
                    {frame} / {Math.max(0, metadata.frameCount - 1)}
                  </output>
                </div>
              </div>
            </div>

            <div className="rounded-panel border border-border bg-surface p-4">
              <div className="grid gap-2 sm:grid-cols-3">
                <AxisSelect
                  label="X"
                  value={search.x}
                  onChange={(x) =>
                    navigate({ search: (previous) => ({ ...previous, x }), replace: true })
                  }
                />
                <AxisSelect
                  label="Y"
                  value={search.y}
                  onChange={(y) =>
                    navigate({ search: (previous) => ({ ...previous, y }), replace: true })
                  }
                />
                <label className="min-w-0">
                  <span className="font-medium text-xs">Color</span>
                  <select
                    value={search.color}
                    onChange={(event) =>
                      navigate({
                        search: (previous) => ({
                          ...previous,
                          color: event.target.value as "none" | "energy",
                        }),
                        replace: true,
                      })
                    }
                    className="mt-1 h-control w-full min-w-0 rounded-control border border-border-strong bg-surface px-2 text-xs"
                  >
                    <option value="none">None</option>
                    <option value="energy">Energy</option>
                  </select>
                </label>
              </div>
            </div>

            <PropertyPlot
              energy={energy}
              frameCount={metadata.frameCount}
              frame={frame}
              x={search.x}
              y={search.y}
              color={search.color}
              onFrameChange={setFrame}
            />
          </section>
        </div>

        <footer className="mt-5 grid gap-px overflow-hidden rounded-panel border border-border bg-border sm:grid-cols-3">
          <InspectorFact label="Loaded role" value={artifact.role} />
          <InspectorFact
            label="Frame properties"
            value={[...metadata.labels.keys()].join(", ") || "Loading"}
          />
          <InspectorFact label="Selected atoms" value={String(metadata.selectedAtoms)} />
        </footer>
      </main>
    </div>
  );
}

function AxisSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: "frame" | "energy";
  onChange: (value: "frame" | "energy") => void;
}) {
  return (
    <label className="min-w-0">
      <span className="font-medium text-xs">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as "frame" | "energy")}
        className="mt-1 h-control w-full min-w-0 rounded-control border border-border-strong bg-surface px-2 text-xs"
      >
        <option value="frame">Frame</option>
        <option value="energy">Energy</option>
      </select>
    </label>
  );
}

function InspectorFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface px-4 py-3">
      <p className="text-subtle-foreground text-xs">{label}</p>
      <p className="mt-0.5 truncate font-mono text-sm">{value}</p>
    </div>
  );
}

function NoInspectableRole({ entry }: { entry: ReturnType<typeof Route.useLoaderData> }) {
  return (
    <section className="page-shell py-20">
      <TriangleAlert className="size-7 text-state-caution" aria-hidden="true" />
      <h1 className="mt-4 font-display font-bold text-3xl tracking-tight">
        This artifact needs a derived inspection record
      </h1>
      <p className="mt-3 max-w-xl text-muted-foreground">
        None of its roles currently declare a bounded browser-readable format and approved HTTP
        source. The original sources remain available from the artifact page.
      </p>
      <Button asChild variant="outline" className="mt-5">
        <Link
          to="/a/$kind/$namespace/$name/$version"
          params={{
            kind: entry.kind,
            namespace: entry.namespace,
            name: entry.name,
            version: entry.version,
          }}
        >
          <ArrowLeft aria-hidden="true" /> Artifact detail
        </Link>
      </Button>
    </section>
  );
}
