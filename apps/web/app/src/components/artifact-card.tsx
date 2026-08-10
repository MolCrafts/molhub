import { Link, useNavigate } from "@tanstack/react-router";
import { Box, Database, Files, HardDrive, Plug } from "lucide-react";

import { KindBadge } from "@/components/kind-badge";
import { formatBytes } from "@/lib/bytes";
import { EntryFacts } from "@/lib/entry-facts";
import type { ArtifactKind, RegistryEntry } from "@/types/registry";

/**
 * Dense catalogue card: identity, short summary, filterable labels, then facts.
 * Coordinates and copy actions belong on the detail page, where there is room
 * to explain them; keeping them here would turn a browse grid into a dashboard.
 */
export function ArtifactCard({ entry }: { entry: RegistryEntry }) {
  const navigate = useNavigate();
  const facts = new EntryFacts(entry);
  const total = formatBytes(facts.size.bytes);
  const targets = facts.targets.slice(0, 2);
  const license = entry.license;
  const visibleTagCount = targets.length + (license ? 1 : 0);
  const remainingTagCount = facts.targets.length + (license ? 1 : 0) - visibleTagCount;

  return (
    <article className="group relative flex min-h-48 flex-col rounded-panel border border-border-strong bg-surface p-4 shadow-raised transition duration-200 ease-standard hover:border-accent-line hover:shadow-overlay">
      <div className="flex min-w-0 items-center gap-2">
        <KindIcon kind={entry.kind} />
        <span className="max-w-28 truncate text-muted-foreground text-sm">{entry.namespace}</span>
        <Link
          to="/a/$kind/$namespace/$name/$version"
          params={{
            kind: entry.kind,
            namespace: entry.namespace,
            name: entry.name,
            version: entry.version,
          }}
          className="min-w-0 font-display font-semibold text-sm outline-none after:absolute after:inset-0 focus-visible:text-accent-ink"
        >
          <span className="block truncate">{entry.name}</span>
        </Link>
        <span className="ml-auto shrink-0 font-mono text-subtle-foreground text-xs">
          @{entry.version}
        </span>
      </div>

      <p className="mt-3 line-clamp-3 text-muted-foreground text-sm leading-relaxed">
        {entry.title}
      </p>

      <div className="relative z-10 mt-3 flex flex-wrap gap-1.5">
        {license ? (
          <button
            type="button"
            onClick={() => navigate({ to: "/explore", search: { license } })}
            className="cursor-pointer rounded-full border border-border-strong px-2 py-0.5 text-muted-foreground text-xs outline-none transition-colors hover:border-accent-line hover:text-accent-ink focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {license}
          </button>
        ) : null}
        {targets.map((target) => (
          <button
            key={`${target.scope}:${target.label}`}
            type="button"
            onClick={() => navigate({ to: "/explore", search: { q: target.label } })}
            className="cursor-pointer rounded-full border border-border-strong px-2 py-0.5 font-mono text-muted-foreground text-xs outline-none transition-colors hover:border-accent-line hover:text-accent-ink focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {target.label}
          </button>
        ))}
        {remainingTagCount > 0 ? (
          <span className="px-1 py-0.5 text-subtle-foreground text-xs">+{remainingTagCount}</span>
        ) : null}
      </div>

      <footer className="mt-auto flex items-center gap-3 pt-4">
        <KindBadge kind={entry.kind} />
        <span className="ml-auto flex items-center gap-1 text-subtle-foreground text-xs">
          <Files className="size-3.5" aria-hidden="true" />
          {facts.fileCount}
        </span>
        <span className="flex items-center gap-1 text-subtle-foreground text-xs">
          <HardDrive className="size-3.5" aria-hidden="true" />
          {total ?? "—"}
        </span>
      </footer>
    </article>
  );
}

function KindIcon({ kind }: { kind: ArtifactKind }) {
  const className = {
    dataset: "bg-kind-dataset-soft text-kind-dataset",
    model: "bg-kind-model-soft text-kind-model",
    plugin: "bg-kind-plugin-soft text-kind-plugin",
  }[kind];

  return (
    <span
      className={`grid size-5 shrink-0 place-items-center rounded-sm [&_svg]:size-3.5 ${className}`}
    >
      {kind === "dataset" ? <Database aria-hidden="true" /> : null}
      {kind === "model" ? <Box aria-hidden="true" /> : null}
      {kind === "plugin" ? <Plug aria-hidden="true" /> : null}
    </span>
  );
}
