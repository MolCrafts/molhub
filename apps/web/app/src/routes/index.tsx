import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowRight, Search } from "lucide-react";
import { type FormEvent, useState } from "react";

import { ArtifactCard } from "@/components/artifact-card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { REGISTRY } from "@/lib/registry";
import type { ArtifactKind } from "@/types/registry";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "MolHub — datasets, models, and plugins" },
      {
        name: "description",
        content: "Find molecular datasets, models, and plugins for Python and the command line.",
      },
    ],
  }),
  component: HomePage,
});

function HomePage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const entries = REGISTRY.entries;
  const kindCounts = countKinds(entries.map((entry) => entry.kind));

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    navigate({ to: "/explore", search: query ? { q: query } : {} });
  }

  return (
    <>
      <section className="mesh-background border-border border-b">
        <div className="page-shell py-10 sm:py-12">
          <div className="max-w-4xl">
            <h1 className="font-display font-bold text-4xl tracking-tight sm:text-5xl">MolHub</h1>
            <p className="mt-3 text-lg text-muted-foreground">
              Find and use molecular datasets, models, and plugins from Python or the command line.
            </p>
          </div>

          <form onSubmit={search} className="mt-6 max-w-3xl">
            <div className="flex gap-1.5 rounded-panel border border-border-strong bg-surface p-1.5 shadow-raised">
              <div className="relative min-w-0 flex-1">
                <Search
                  className="absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle-foreground"
                  aria-hidden="true"
                />
                <Input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="h-10 border-transparent bg-transparent pr-2 pl-9 focus-visible:border-transparent focus-visible:ring-0"
                  placeholder="Search datasets, models, plugins"
                  aria-label="Search the MolHub registry"
                />
              </div>
              <Button type="submit">
                Search <ArrowRight aria-hidden="true" />
              </Button>
            </div>
          </form>
        </div>
      </section>

      <section className="page-shell py-10 sm:py-12">
        <div className="flex items-center justify-between gap-4">
          <h2 className="font-display font-bold text-2xl tracking-tight">Registry</h2>
          <Button asChild variant="link">
            <Link to="/explore" search={{}}>
              Browse all <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        </div>

        <nav className="mt-4 flex flex-wrap gap-2" aria-label="Browse by type">
          <KindFilter kind="dataset" count={kindCounts.dataset} />
          <KindFilter kind="model" count={kindCounts.model} />
          <KindFilter kind="plugin" count={kindCounts.plugin} />
        </nav>

        <div className="mt-5 grid gap-3 lg:grid-cols-3">
          {entries.slice(0, 3).map((entry) => (
            <ArtifactCard key={entry.coordinate} entry={entry} />
          ))}
        </div>
      </section>

      <section className="border-border border-t">
        <div className="page-shell flex flex-col gap-5 py-7 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="font-display font-bold text-xl">Publish a dataset, model, or plugin</h2>
            <p className="mt-1 text-muted-foreground text-sm">Submit a manifest for review.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild>
              <Link to="/submit">Submit manifest</Link>
            </Button>
            <Button asChild variant="outline">
              <a
                href="https://github.com/MolCrafts/molhub-registry"
                target="_blank"
                rel="noreferrer"
              >
                Registry repository
              </a>
            </Button>
          </div>
        </div>
      </section>
    </>
  );
}

function KindFilter({ kind, count }: { kind: ArtifactKind; count: number }) {
  return (
    <Link
      to="/explore"
      search={{ kind }}
      className="inline-flex items-center gap-2 rounded-full border border-border-strong bg-surface px-3 py-1.5 font-medium text-muted-foreground text-sm transition-colors hover:border-accent-line hover:text-accent-ink"
    >
      <span className="capitalize">{kind}s</span>
      <span className="font-mono text-subtle-foreground text-xs">{count}</span>
    </Link>
  );
}

function countKinds(kinds: ArtifactKind[]): Record<ArtifactKind, number> {
  const result: Record<ArtifactKind, number> = { dataset: 0, model: 0, plugin: 0 };
  for (const kind of kinds) result[kind] += 1;
  return result;
}
