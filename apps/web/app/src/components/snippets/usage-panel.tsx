import { Code } from "@/components/ui/code";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { RegistryEntry } from "@/types/registry";
import { cliSnippet } from "./cli";
import { pythonSnippet } from "./python";
import { SnippetBlock } from "./snippet-block";
import { typescriptSnippet } from "./typescript";

/**
 * The three ways to use this entry, in the three languages molhub speaks.
 *
 * Every snippet names the **full** coordinate. The shorthand `qm9@v2` is
 * pleasant to type and wrong to paste: it expands to `dataset:molcrafts/…`
 * from defaults, so a snippet that used it would keep resolving against the
 * old namespace the day this entry moved, with nothing to show for it.
 */
export function UsagePanel({ entry }: { entry: RegistryEntry }) {
  const snippets = [pythonSnippet(entry), cliSnippet(entry), typescriptSnippet(entry)];

  return (
    <section aria-labelledby="detail-usage" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h2 id="detail-usage" className="font-display font-bold text-2xl tracking-tight">
          Usage
        </h2>
        <p className="text-sm text-muted-foreground">
          Full coordinate: <Code>{entry.coordinate}</Code>
        </p>
      </div>

      <Tabs defaultValue="python">
        <TabsList aria-label="Snippet language">
          {snippets.map((snippet) => (
            <TabsTrigger key={snippet.language} value={snippet.language}>
              {snippet.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {snippets.map((snippet) => (
          <TabsContent key={snippet.language} value={snippet.language}>
            <SnippetBlock snippet={snippet} />
          </TabsContent>
        ))}
      </Tabs>
    </section>
  );
}
