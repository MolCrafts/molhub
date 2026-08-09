import { Slot } from "@radix-ui/react-slot";
import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

/* No destructive variant: submission creates review records but the public UI
 * has no delete or irreversible action. */
const buttonVariants = cva(
  cn(
    "inline-flex shrink-0 items-center justify-center gap-1.5 whitespace-nowrap",
    "rounded-control font-medium",
    "transition-colors duration-(--motion-fast) ease-standard",
    "outline-none focus-visible:ring-2 focus-visible:ring-ring/60 focus-visible:ring-offset-1 focus-visible:ring-offset-background",
    "disabled:pointer-events-none disabled:opacity-50",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ),
  {
    variants: {
      variant: {
        default: "bg-accent text-accent-foreground hover:bg-accent-hover active:bg-accent-active",
        outline:
          "border border-border-strong bg-transparent text-foreground hover:bg-interactive active:bg-interactive-active",
        subtle: "bg-sunken text-foreground hover:bg-interactive active:bg-interactive-active",
        ghost:
          "bg-transparent text-muted-foreground hover:bg-interactive hover:text-foreground active:bg-interactive-active",
        link: "bg-transparent text-accent-ink underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-control-compact px-2.5 text-label",
        default: "h-control px-3 text-meta",
        lg: "h-control-comfortable px-4 text-body",
        icon: "size-control",
        "icon-sm": "size-control-compact",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : "button";

  return (
    <Comp
      data-slot="button"
      // A bare <button> defaults to type="submit", so the first one placed
      // inside a form would reload the page instead of doing its job — a bug
      // that only appears once someone adds a form and is baffling when it
      // does. Only for a real button: with `asChild` the child may be an
      // anchor, where the attribute is meaningless. An explicit `type` in
      // props still wins, because it is spread after this.
      {...(asChild ? {} : { type: "button" as const })}
      data-variant={variant ?? "default"}
      // Link-styled buttons sit inside prose, so they opt out of the
      // coarse-pointer 44px expansion applied in base CSS.
      {...(variant === "link" ? { "data-inline": "" } : {})}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants };
