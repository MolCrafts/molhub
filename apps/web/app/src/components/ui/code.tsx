import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

/*
 * Nearly every load-bearing string in this registry is machine syntax —
 * coordinates (`dataset:molcrafts/qm9@v2`), locators, SPDX ids, DOIs, and
 * digests — so `Code` is a primary text style here rather than documentation
 * decoration. The mono face and its optical size correction come from base CSS.
 */
const codeVariants = cva("rounded-control bg-sunken font-mono text-foreground", {
  variants: {
    variant: {
      /** Sits inside a sentence or a table cell. */
      inline: "px-1 py-px",
      /** Own line: locator lists, digests, copy-me coordinates. */
      block: "block w-full overflow-x-auto px-2 py-1.5",
    },
    /** Long digests and locators would otherwise widen their column. */
    wrap: {
      none: "whitespace-nowrap",
      anywhere: "[overflow-wrap:anywhere]",
    },
  },
  defaultVariants: {
    variant: "inline",
    wrap: "none",
  },
});

function Code({
  className,
  variant,
  wrap,
  ...props
}: React.ComponentProps<"code"> & VariantProps<typeof codeVariants>) {
  return (
    <code data-slot="code" className={cn(codeVariants({ variant, wrap }), className)} {...props} />
  );
}

export { Code, codeVariants };
