import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Single-line text input.
 *
 * Sized at `control-comfortable` because the registry's dominant input is the
 * search field at the top of the directory, not a form cell.
 */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-control-comfortable w-full min-w-0 rounded-control border border-border-strong",
        "bg-surface px-2.5 text-body text-foreground",
        "transition-colors duration-(--motion-fast) ease-standard",
        "placeholder:text-subtle-foreground",
        "selection:bg-accent selection:text-accent-foreground",
        "outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
        "disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-state-critical aria-invalid:ring-2 aria-invalid:ring-state-critical/30",
        // The clear affordance on `type="search"` is Safari-only chrome that
        // does not follow the theme; the app renders its own reset control.
        "[&::-webkit-search-cancel-button]:appearance-none",
        className,
      )}
      {...props}
    />
  );
}

export { Input };
