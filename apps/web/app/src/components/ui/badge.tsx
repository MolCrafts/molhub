import { type VariantProps, cva } from "class-variance-authority";
import type * as React from "react";

import { cn } from "@/lib/utils";

/**
 * The registry state vocabulary.
 *
 * molhub is a registry, not a task runner: it has no jobs, so it carries none
 * of the MolCrafts job-status set (draft/ready/queued/running/completed/…).
 * These four tones describe what a *manifest* actually expresses. See
 * `styles/README.md` for the manifest-field → tone mapping and for why
 * `attested` is deliberately not green.
 */
export type BadgeTone =
  /** Structural facts with no judgement attached: kind, licence id, version. */
  | "neutral"
  /** The current selection, or the artifact's own coordinate. */
  | "accent"
  /** Upstream published something we copied verbatim: a digest, extra mirrors. */
  | "attested"
  /** A gap a reuser must notice before depending on this entry. */
  | "caution"
  /** Still resolvable, no longer the head: a superseded version. */
  | "archival"
  /** The registry itself failed to load or parse. */
  | "critical";

/*
 * Tone sets three custom properties; variant decides how they are consumed.
 * That keeps this at 6 tone rules + 2 variant rules instead of 12 compound
 * variants, and adding a tone later stays a one-line change.
 */
const badgeVariants = cva(
  cn(
    "inline-flex w-fit shrink-0 items-center gap-1 whitespace-nowrap",
    "rounded-control border font-medium",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3",
  ),
  {
    variants: {
      tone: {
        neutral: cn(
          "[--badge-fill:var(--color-sunken)]",
          "[--badge-line:var(--color-border-strong)]",
          "[--badge-ink:var(--color-muted-foreground)]",
        ),
        accent: cn(
          "[--badge-fill:var(--color-accent-soft)]",
          "[--badge-line:var(--color-accent-line)]",
          "[--badge-ink:var(--color-accent-ink)]",
        ),
        attested: cn(
          "[--badge-fill:var(--color-state-attested-soft)]",
          "[--badge-line:var(--color-state-attested-line)]",
          "[--badge-ink:var(--color-state-attested)]",
        ),
        caution: cn(
          "[--badge-fill:var(--color-state-caution-soft)]",
          "[--badge-line:var(--color-state-caution-line)]",
          "[--badge-ink:var(--color-state-caution)]",
        ),
        archival: cn(
          "[--badge-fill:var(--color-state-archival-soft)]",
          "[--badge-line:var(--color-state-archival-line)]",
          "[--badge-ink:var(--color-state-archival)]",
        ),
        critical: cn(
          "[--badge-fill:var(--color-state-critical-soft)]",
          "[--badge-line:var(--color-state-critical-line)]",
          "[--badge-ink:var(--color-state-critical)]",
        ),
      },
      variant: {
        soft: "border-transparent bg-(--badge-fill) text-(--badge-ink)",
        outline: "border-(--badge-line) bg-transparent text-(--badge-ink)",
      },
      size: {
        default: "px-1.5 py-0.5 text-label",
        sm: "px-1 py-0 text-micro",
      },
    },
    defaultVariants: {
      tone: "neutral",
      variant: "soft",
      size: "default",
    },
  },
);

function Badge({
  className,
  tone,
  variant,
  size,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span
      data-slot="badge"
      data-tone={tone ?? "neutral"}
      className={cn(badgeVariants({ tone, variant, size }), className)}
      {...props}
    />
  );
}

export { Badge, badgeVariants };
