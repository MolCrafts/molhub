import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/*
 * tailwind-merge only knows Tailwind's stock scales. Our theme adds named
 * values (`text-body`, `h-control`, `rounded-panel`, `max-w-content`), and
 * without registering them the merge is actively wrong in two ways:
 *
 *   text-body + text-muted-foreground  ->  text-body is DROPPED
 *       (`text-*` falls through to the colour group, whose validator matches
 *        anything, so the size looks like a competing colour)
 *   h-control + h-control-comfortable  ->  BOTH kept
 *       (unrecognised values are never treated as conflicting, so a caller's
 *        override loses or wins by CSS source order rather than by intent)
 *
 * Registering the scales below is what makes `className` overrides behave.
 * Keep these lists in sync with the matching blocks in ../styles/tailwind.css.
 */

/** `--text-*` in the theme block. */
const FONT_SIZES = ["micro", "label", "meta", "body", "title", "heading", "display"] as const;

/** `--spacing-*` named control geometry. */
const CONTROL_SIZES = [
  "control",
  "control-compact",
  "control-comfortable",
  "touch-target",
  "header",
  "row",
  "row-compact",
] as const;

/** `--radius-*` roles, backed by the three brand radii. */
const RADII = ["control", "panel", "overlay"] as const;

/** `--container-*` width caps. */
const CONTAINERS = ["content", "prose-measure", "rail"] as const;

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: [...FONT_SIZES] }],
      h: [{ h: [...CONTROL_SIZES] }],
      "min-h": [{ "min-h": [...CONTROL_SIZES] }],
      w: [{ w: [...CONTROL_SIZES, ...CONTAINERS] }],
      size: [{ size: [...CONTROL_SIZES] }],
      "max-w": [{ "max-w": [...CONTAINERS] }],
      rounded: [{ rounded: [...RADII] }],
    },
  },
});

/**
 * Merge class names, letting later Tailwind utilities win over earlier ones.
 *
 * Every primitive under `components/ui/` composes its classes through this, so
 * a caller's `className` can always override a default without `!important`
 * or ordering luck.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
