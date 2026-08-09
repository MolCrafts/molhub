import { Check, Copy, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type CopyState = "idle" | "copied" | "failed";

/** Long enough to be read, short enough that the button is ready again. */
const RESET_AFTER_MS = 2200;

export interface CopyButtonProps {
  /** Exactly what lands on the clipboard. */
  text: string;
  /** What is being copied, for the accessible name: "the Python snippet". */
  subject: string;
  className?: string;
}

/**
 * Copy `text` to the clipboard, and say whether it worked.
 *
 * A plain `<button>`, so it is in the tab order and fires on Enter and Space
 * with no key handling of our own. The outcome is announced through a
 * `role="status"` region rather than only through the icon, because the whole
 * point of the control is confirmation and an icon swap is invisible to a
 * screen reader.
 *
 * The clipboard API rejects outside a secure context and when permission is
 * refused. That is reported, never swallowed: a silent no-op would leave the
 * reader pasting whatever they copied an hour ago.
 */
export function CopyButton({ text, subject, className }: CopyButtonProps) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const copy = useCallback(() => {
    if (timer.current !== null) clearTimeout(timer.current);

    const settle = (next: CopyState) => {
      setState(next);
      timer.current = setTimeout(() => setState("idle"), RESET_AFTER_MS);
    };

    const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
    if (!clipboard) {
      settle("failed");
      return;
    }
    clipboard.writeText(text).then(
      () => settle("copied"),
      () => settle("failed"),
    );
  }, [text]);

  const message =
    state === "copied"
      ? `Copied ${subject} to the clipboard.`
      : state === "failed"
        ? `Could not reach the clipboard. Select ${subject} and copy it manually.`
        : "";

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {/* Decorative twin of the status region below; hidden so the outcome is
          announced once, not twice. */}
      <p
        aria-hidden="true"
        className={cn(
          "text-label",
          state === "failed" ? "text-state-caution" : "text-muted-foreground",
        )}
      >
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : null}
      </p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={copy}
        aria-label={`Copy ${subject}`}
        data-state={state}
      >
        {state === "copied" ? (
          <Check aria-hidden="true" />
        ) : state === "failed" ? (
          <TriangleAlert aria-hidden="true" />
        ) : (
          <Copy aria-hidden="true" />
        )}
        Copy
      </Button>
      {/* `<output>` carries an implicit `role="status"`, so the outcome is
          announced without a redundant ARIA attribute. */}
      <output className="sr-only">{message}</output>
    </div>
  );
}
