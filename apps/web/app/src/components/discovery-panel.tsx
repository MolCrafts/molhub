import { Search, SlidersHorizontal, X } from "lucide-react";
import { useMemo } from "react";

import { ArtifactCard } from "@/components/artifact-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { RegistrySearch } from "@/lib/search";
import { cn } from "@/lib/utils";
import type { ArtifactKind, RegistryEntry } from "@/types/registry";

export interface DiscoveryFilters {
  q?: string;
  kind?: ArtifactKind;
  license?: string;
  source?: string;
}

export interface DiscoveryPanelProps {
  entries: RegistryEntry[];
  filters: DiscoveryFilters;
  onChange: (filters: DiscoveryFilters) => void;
}

const kinds: Array<{ label: string; value?: ArtifactKind }> = [
  { label: "All" },
  { label: "Datasets", value: "dataset" },
  { label: "Models", value: "model" },
  { label: "Plugins", value: "plugin" },
];

export function DiscoveryPanel({ entries, filters, onChange }: DiscoveryPanelProps) {
  const search = useMemo(() => new RegistrySearch(entries), [entries]);
  const licenses = useMemo(
    () => [...new Set(entries.flatMap((entry) => (entry.license ? [entry.license] : [])))].sort(),
    [entries],
  );
  const sources = useMemo(
    () =>
      [
        ...new Set(
          entries.flatMap((entry) =>
            entry.artifacts.flatMap((artifact) => artifact.locators.map(schemeOf)),
          ),
        ),
      ].sort(),
    [entries],
  );
  const results = useMemo(() => {
    return search.matches(filters.q ?? "").filter((entry) => {
      if (filters.kind && entry.kind !== filters.kind) return false;
      if (filters.license && entry.license !== filters.license) return false;
      if (
        filters.source &&
        !entry.artifacts.some((artifact) =>
          artifact.locators.some((locator) => schemeOf(locator) === filters.source),
        )
      ) {
        return false;
      }
      return true;
    });
  }, [filters, search]);

  const active = Boolean(filters.q || filters.kind || filters.license || filters.source);

  return (
    <section aria-label="Registry search">
      <div className="rounded-panel border border-border bg-surface p-3 sm:p-4">
        <div className="relative">
          <Search
            className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-subtle-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            aria-label="Search artifacts"
            value={filters.q ?? ""}
            onChange={(event) => onChange({ ...filters, q: event.target.value || undefined })}
            placeholder="Search coordinates, titles, files"
            className="h-11 rounded-control border-transparent bg-sunken pr-12 pl-12 focus-visible:bg-surface"
          />
          {filters.q ? (
            <Button
              variant="ghost"
              size="icon"
              className="absolute top-1/2 right-2 -translate-y-1/2"
              aria-label="Clear search"
              onClick={() => onChange({ ...filters, q: undefined })}
            >
              <X aria-hidden="true" />
            </Button>
          ) : null}
        </div>

        <div className="mt-3 flex flex-col gap-3 lg:flex-row lg:items-center">
          <div className="flex gap-1 overflow-x-auto" aria-label="Artifact type">
            {kinds.map((kind) => (
              <button
                key={kind.label}
                type="button"
                aria-pressed={filters.kind === kind.value}
                className={cn(
                  "shrink-0 rounded-control px-3 py-1.5 font-medium text-sm transition",
                  filters.kind === kind.value
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-sunken hover:text-foreground",
                )}
                onClick={() => onChange({ ...filters, kind: kind.value })}
              >
                {kind.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2 lg:ml-auto">
            <SlidersHorizontal className="size-4 text-subtle-foreground" aria-hidden="true" />
            <select
              aria-label="Filter by license"
              value={filters.license ?? ""}
              onChange={(event) =>
                onChange({ ...filters, license: event.target.value || undefined })
              }
              className="h-9 rounded-control border border-border bg-background px-2.5 text-sm outline-none focus:ring-2 focus:ring-ring/40"
            >
              <option value="">All licenses</option>
              {licenses.map((license) => (
                <option key={license}>{license}</option>
              ))}
            </select>
            <select
              aria-label="Filter by source"
              value={filters.source ?? ""}
              onChange={(event) =>
                onChange({ ...filters, source: event.target.value || undefined })
              }
              className="h-9 rounded-control border border-border bg-background px-2.5 text-sm outline-none focus:ring-2 focus:ring-ring/40"
            >
              <option value="">All sources</option>
              {sources.map((source) => (
                <option key={source}>{source}</option>
              ))}
            </select>
            {active ? (
              <Button variant="ghost" size="sm" onClick={() => onChange({})}>
                Reset
              </Button>
            ) : null}
          </div>
        </div>
      </div>

      <div className="mt-6 flex items-end justify-between gap-4">
        <p className="font-display font-semibold text-lg tracking-tight">
          {results.length} {results.length === 1 ? "result" : "results"}
        </p>
      </div>

      {results.length === 0 ? (
        <div className="mt-5 rounded-panel border border-dashed border-border-strong bg-surface py-12 text-center">
          <p className="font-display font-semibold text-2xl">No results</p>
          <p className="mt-2 text-muted-foreground">Try a broader query or clear the filters.</p>
          <Button className="mt-5" variant="outline" onClick={() => onChange({})}>
            Clear filters
          </Button>
        </div>
      ) : (
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {results.map((entry) => (
            <ArtifactCard key={entry.coordinate} entry={entry} />
          ))}
        </div>
      )}
    </section>
  );
}

function schemeOf(locator: string): string {
  const separator = locator.indexOf("://");
  return separator === -1 ? "https" : locator.slice(0, separator);
}
