import { createFileRoute } from "@tanstack/react-router";
import { z } from "zod";

import { type DiscoveryFilters, DiscoveryPanel } from "@/components/discovery-panel";
import { REGISTRY } from "@/lib/registry";

const searchSchema = z.object({
  q: z.string().optional().catch(undefined),
  kind: z.enum(["dataset", "model", "plugin"]).optional().catch(undefined),
  license: z.string().optional().catch(undefined),
  source: z.string().optional().catch(undefined),
});

export const Route = createFileRoute("/explore")({
  validateSearch: searchSchema,
  head: () => ({
    meta: [
      { title: "Registry — MolHub" },
      {
        name: "description",
        content: "Search molecular datasets, models, and plugins by name, license, or source.",
      },
    ],
  }),
  component: ExplorePage,
});

function ExplorePage() {
  const filters = Route.useSearch();
  const navigate = Route.useNavigate();

  function update(next: DiscoveryFilters) {
    navigate({ search: next, replace: true });
  }

  return (
    <div className="page-shell py-8 sm:py-10">
      <header>
        <h1 className="font-display font-bold text-3xl tracking-tight sm:text-4xl">Registry</h1>
        <p className="mt-2 text-muted-foreground">
          Search by name, license, source, or scientific property.
        </p>
      </header>

      <div className="mt-6">
        <DiscoveryPanel entries={REGISTRY.entries} filters={filters} onChange={update} />
      </div>
    </div>
  );
}
