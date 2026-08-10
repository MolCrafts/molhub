import { Box, Database, Plug } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ArtifactKind } from "@/types/registry";

const styles: Record<ArtifactKind, string> = {
  dataset: "bg-kind-dataset-soft text-kind-dataset",
  model: "bg-kind-model-soft text-kind-model",
  plugin: "bg-kind-plugin-soft text-kind-plugin",
};

export function KindBadge({ kind, className }: { kind: ArtifactKind; className?: string }) {
  const Icon = kind === "dataset" ? Database : kind === "model" ? Box : Plug;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold text-xs capitalize",
        styles[kind],
        className,
      )}
    >
      <Icon className="size-3.5" aria-hidden="true" />
      {kind}
    </span>
  );
}
