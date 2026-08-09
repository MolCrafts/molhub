import { FileQuestion, PackageOpen, SearchX } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Code } from "@/components/ui/code";
import { EmptyState } from "@/components/ui/empty-state";

/**
 * What this site renders when it has nothing to render.
 *
 * Three different absences, three different explanations. They are together
 * because they answer one question — "why is this page not showing me
 * anything?" — and apart from everything else because a blank rectangle is the
 * failure each of them exists to prevent.
 */

/**
 * No manifests at all: a fresh fork, or a registry whose `artifacts/` is
 * empty. Not an error — the build succeeded, there is simply nothing catalogued
 * yet — so it says what to do next instead of apologising.
 */
export function RegistryEmpty() {
  return (
    <EmptyState
      icon={<PackageOpen className="size-6" aria-hidden="true" />}
      title="Nothing is catalogued yet"
      description="This build found no manifests. A registry entry is one YAML file at artifacts/<kind>/<namespace>/<name>/<version>.yaml — merge one and it appears here on the next deploy."
      action={
        <Button asChild variant="outline" size="sm">
          <a
            href="https://github.com/MolCrafts/molhub-registry#adding-a-dataset"
            target="_blank"
            rel="noreferrer noopener"
          >
            How to add a dataset
          </a>
        </Button>
      }
    />
  );
}

/** The query excluded everything. Routine, so it is muted and offers the way back. */
export function NoMatches({ query, onClear }: { query: string; onClear: () => void }) {
  return (
    <EmptyState
      icon={<SearchX className="size-6" aria-hidden="true" />}
      title={`Nothing matches “${query}”`}
      description="Search covers coordinates, titles, descriptions, declared targets, and the roles and filenames of an entry's files. Every word has to match — try one of them on its own."
      action={
        <Button variant="outline" size="sm" onClick={onClear}>
          Clear the search
        </Button>
      }
    />
  );
}

/**
 * A URL naming a coordinate this registry does not hold.
 *
 * Almost always a hand-edited or stale link, so it repeats the coordinate
 * verbatim — the difference between `@v2` and `@v4` is the entire message, and
 * a generic "not found" hides exactly the character that is wrong.
 */
export function UnknownCoordinate({ coordinate }: { coordinate: string }) {
  return (
    <EmptyState
      icon={<FileQuestion className="size-6" aria-hidden="true" />}
      title="That coordinate is not in this registry"
      description="A coordinate names one artifact version and never changes meaning, so a version that once resolved still exists — but a mistyped name or a manifest that was never merged has nothing behind it."
      action={
        <div className="flex flex-col items-center gap-3">
          <Code variant="block" wrap="anywhere" className="text-center">
            {coordinate}
          </Code>
          <Button asChild variant="outline" size="sm">
            <a href="#/">Browse the registry</a>
          </Button>
        </div>
      }
    />
  );
}
