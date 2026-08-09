import type * as React from "react";

import { cn } from "@/lib/utils";

export type EmptyStateDensity = "default" | "compact" | "inline";

export interface EmptyStateProps extends React.ComponentProps<"div"> {
  /** What is absent, stated plainly: "No datasets match these filters". */
  title: string;
  /** How to get somewhere from here. Optional — omit rather than pad. */
  description?: string;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  density?: EmptyStateDensity;
}

const CONTAINER: Record<EmptyStateDensity, string> = {
  default: "flex flex-col items-center gap-1.5 px-4 py-12 text-center",
  compact: "flex flex-col items-center gap-1 px-3 py-6 text-center",
  inline: "flex flex-col gap-0.5 px-1 py-1.5 text-left",
};

const TITLE: Record<EmptyStateDensity, string> = {
  default: "text-title text-foreground",
  compact: "text-body text-foreground",
  inline: "text-meta text-muted-foreground",
};

const DESCRIPTION: Record<EmptyStateDensity, string> = {
  default: "max-w-prose-measure text-body text-muted-foreground",
  compact: "text-meta text-muted-foreground",
  inline: "text-micro text-subtle-foreground",
};

/**
 * The "nothing here" surface, at three densities.
 *
 * A directory is mostly filters, so an empty result set is a routine state
 * rather than an error — hence muted type and no critical tone. Reserve
 * `Badge tone="critical"` for the registry itself failing to load.
 */
function EmptyState({
  title,
  description,
  action,
  icon,
  density = "default",
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div data-slot="empty-state" className={cn(CONTAINER[density], className)} {...props}>
      {icon ? <div className="text-subtle-foreground">{icon}</div> : null}
      <p className={TITLE[density]}>{title}</p>
      {description ? <p className={DESCRIPTION[density]}>{description}</p> : null}
      {action ? <div className={density === "inline" ? "mt-1" : "mt-3"}>{action}</div> : null}
    </div>
  );
}

export { EmptyState };
