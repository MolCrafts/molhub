import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Signal } from "@/lib/entry-facts";

/**
 * A state badge that can explain itself.
 *
 * `no digest` and `single source` are the two chips a reuser must actually
 * understand before depending on an entry, and neither is self-explanatory at
 * 11px. The trigger is a real `<button>` rather than a `<span>` with a
 * `tabIndex`, so the explanation is reachable by keyboard and announced as an
 * interactive element instead of being hover-only trivia.
 */
export function SignalBadge({ signal }: { signal: Signal }) {
  return (
    <Tooltip>
      <TooltipTrigger className="rounded-control outline-none focus-visible:ring-2 focus-visible:ring-ring/60">
        <Badge tone={signal.tone} size="sm">
          {signal.label}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{signal.detail}</TooltipContent>
    </Tooltip>
  );
}
