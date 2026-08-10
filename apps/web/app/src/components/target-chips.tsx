import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { TargetChip } from "@/lib/entry-facts";

/** QM9 declares fifteen. Past this, a row stops being scannable. */
const SHOWN = 4;

/**
 * The properties an entry declares it carries.
 *
 * Graph-level targets are filled, per-atom ones are outlined — one visual axis,
 * not a second colour, because `kind` and the state vocabulary have already
 * spent the row's colour budget. The header this sits under carries the legend.
 *
 * `targets` is declarative in the manifest: nothing parses bytes according to
 * it. So the empty case says "none declared" rather than "none", which would
 * claim the file has no properties in it.
 */
export function TargetChips({ targets }: { targets: TargetChip[] }) {
  if (targets.length === 0) {
    return <span className="text-meta text-subtle-foreground">none declared</span>;
  }

  const shown = targets.slice(0, SHOWN);
  const rest = targets.slice(SHOWN);

  return (
    <div className="flex flex-wrap items-center gap-1">
      {shown.map((target) => (
        <Badge
          key={`${target.scope}:${target.label}`}
          size="sm"
          variant={target.scope === "atom" ? "outline" : "soft"}
          className="font-mono"
        >
          {target.label}
        </Badge>
      ))}
      {rest.length > 0 ? (
        <Tooltip>
          <TooltipTrigger className="rounded-control outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
            <Badge size="sm">+{rest.length}</Badge>
          </TooltipTrigger>
          <TooltipContent>{rest.map((target) => target.label).join(", ")}</TooltipContent>
        </Tooltip>
      ) : null}
    </div>
  );
}
