import * as TabsPrimitive from "@radix-ui/react-tabs";
import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Tabs for the entry detail view (Artifacts / Targets / Usage).
 *
 * The default is `line`, not the segmented pill: a registry page is a column
 * of text, and an underline adds a rule where a filled control would add a
 * card. `segmented` stays available for compact in-panel switches.
 */
function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("group/tabs flex flex-col gap-3", className)}
      {...props}
    />
  );
}

const tabsListVariants = cva("group/tabs-list inline-flex w-fit items-center", {
  variants: {
    variant: {
      line: "h-control-comfortable gap-4 border-border border-b",
      segmented: "h-control gap-1 rounded-panel bg-sunken p-1",
    },
  },
  defaultVariants: {
    variant: "line",
  },
});

function TabsList({
  className,
  variant = "line",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-full items-center justify-center gap-1.5 whitespace-nowrap",
        "font-medium text-meta text-muted-foreground",
        "transition-colors duration-(--motion-fast) ease-standard",
        "hover:text-foreground",
        "outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
        "disabled:pointer-events-none disabled:opacity-50",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        // Line: an accent rule sitting on the list's own border, no fill.
        "group-data-[variant=line]/tabs-list:rounded-none",
        "group-data-[variant=line]/tabs-list:data-[state=active]:text-foreground",
        "group-data-[variant=line]/tabs-list:after:absolute group-data-[variant=line]/tabs-list:after:inset-x-0",
        "group-data-[variant=line]/tabs-list:after:-bottom-px group-data-[variant=line]/tabs-list:after:h-0.5",
        "group-data-[variant=line]/tabs-list:after:bg-accent group-data-[variant=line]/tabs-list:after:opacity-0",
        "group-data-[variant=line]/tabs-list:after:transition-opacity",
        "group-data-[variant=line]/tabs-list:after:duration-(--motion-fast)",
        "group-data-[variant=line]/tabs-list:data-[state=active]:after:opacity-100",
        // Segmented: the active tab lifts onto the raised surface.
        "group-data-[variant=segmented]/tabs-list:rounded-control",
        "group-data-[variant=segmented]/tabs-list:px-2.5",
        "group-data-[variant=segmented]/tabs-list:data-[state=active]:bg-surface",
        "group-data-[variant=segmented]/tabs-list:data-[state=active]:text-foreground",
        "group-data-[variant=segmented]/tabs-list:data-[state=active]:shadow-raised",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("outline-none", className)}
      {...props}
    />
  );
}

export { Tabs, TabsContent, TabsList, TabsTrigger, tabsListVariants };
