import { Badge } from "@/components/ui/badge";
import { Code } from "@/components/ui/code";
import { cn } from "@/lib/utils";
import { CopyButton } from "./copy-button";
import type { Snippet } from "./snippet";

/**
 * One snippet: a caption, a copy control, and the code.
 *
 * Colouring is one distinction only — commentary versus code — done by line
 * prefix rather than by a lexer. A snippet is three to twelve lines of a
 * language whose grammar this site has no business knowing, and the design
 * system's whole argument is that colour marks deviation; a rainbow here would
 * spend the budget on decoration.
 */
export function SnippetBlock({ snippet }: { snippet: Snippet }) {
  const lines = snippet.code.split("\n");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2 text-meta text-muted-foreground">
          {snippet.availability === "forthcoming" ? (
            <Badge tone="caution" variant="outline" size="sm">
              not published yet
            </Badge>
          ) : null}
          <span>{snippet.caption}</span>
        </p>
        <CopyButton text={snippet.code} subject={`the ${snippet.label} snippet`} />
      </div>

      <pre className="overflow-x-auto rounded-panel border border-border bg-sunken px-3 py-2.5">
        <Code className="bg-transparent p-0 text-meta">
          {lines.map((line, index) => (
            <span
              // Lines are positional and the block never reorders, so the index
              // is the identity here.
              // biome-ignore lint/suspicious/noArrayIndexKey: static, never reordered
              key={index}
              className={cn(
                "block",
                line.trimStart().startsWith(snippet.commentPrefix)
                  ? "text-subtle-foreground"
                  : "text-foreground",
              )}
            >
              {line === "" ? " " : line}
            </span>
          ))}
        </Code>
      </pre>
    </div>
  );
}
