import { Coordinate } from "@molcrafts/molhub/core";
import { createFileRoute } from "@tanstack/react-router";
import {
  CheckCircle2,
  ExternalLink,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { type ComponentProps, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type ReviewerSubmission,
  SubmissionApiError,
  SubmissionClient,
  type SubmissionStatus,
} from "@/lib/submissions";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/review")({
  head: () => ({
    meta: [
      { title: "Review submissions — MolHub" },
      { name: "robots", content: "noindex, nofollow" },
    ],
  }),
  component: ReviewPage,
});

type QueueFilter = SubmissionStatus | "all";

function ReviewPage() {
  const [token, setToken] = useState("");
  const [filter, setFilter] = useState<QueueFilter>("pending");
  const [queue, setQueue] = useState<readonly ReviewerSubmission[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = useMemo(
    () => queue?.find((submission) => submission.id === selectedId) ?? queue?.[0] ?? null,
    [queue, selectedId],
  );

  async function loadQueue(nextFilter = filter) {
    if (!token.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const submissions = await new SubmissionClient().reviewQueue(token.trim(), nextFilter);
      setQueue(submissions);
      setSelectedId((current) =>
        submissions.some((submission) => submission.id === current)
          ? current
          : (submissions[0]?.id ?? null),
      );
    } catch (reason) {
      setError(messageOf(reason));
      setQueue(null);
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: "approve" | "reject") {
    if (!selected || busy) return;
    if (decision === "reject" && !note.trim()) {
      setError("Explain what the contributor needs to change before rejecting.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await new SubmissionClient().review(selected.id, decision, token.trim(), note);
      setNote("");
      await loadQueue();
    } catch (reason) {
      setError(messageOf(reason));
      setBusy(false);
    }
  }

  function changeFilter(value: QueueFilter) {
    setFilter(value);
    if (queue) void loadQueue(value);
  }

  return (
    <>
      <section className="mesh-background border-border border-b">
        <div className="page-shell py-8 sm:py-10">
          <p className="flex items-center gap-2 font-mono text-accent-ink text-xs uppercase tracking-wide">
            <ShieldCheck className="size-4" aria-hidden="true" /> Registry operations
          </p>
          <h1 className="mt-2 font-display font-bold text-3xl tracking-tight sm:text-4xl">
            Review submissions
          </h1>
        </div>
      </section>

      <div className="page-shell py-8 lg:py-10">
        <section className="rounded-panel border border-border bg-surface p-4 sm:p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-end">
            <div className="min-w-0 flex-1">
              <label htmlFor="admin-token" className="flex items-center gap-2 font-medium text-sm">
                <LockKeyhole className="size-4 text-accent-ink" aria-hidden="true" /> Admin token
              </label>
              <p className="mt-1 text-subtle-foreground text-xs">
                Kept only in this page's memory and sent to the protected API.
              </p>
              <Input
                id="admin-token"
                type="password"
                autoComplete="current-password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void loadQueue();
                }}
                className="mt-2"
              />
            </div>
            <label className="min-w-44 font-medium text-sm">
              Queue
              <select
                value={filter}
                onChange={(event) => changeFilter(event.target.value as QueueFilter)}
                className="mt-2 h-control w-full rounded-control border border-input bg-background px-3 text-sm"
              >
                <option value="pending">Pending</option>
                <option value="reviewing">Reviewing</option>
                <option value="accepted">Accepted</option>
                <option value="rejected">Rejected</option>
                <option value="all">All</option>
              </select>
            </label>
            <Button disabled={!token.trim() || busy} onClick={() => void loadQueue()}>
              <RefreshCw className={cn(busy && "animate-spin")} aria-hidden="true" /> Load queue
            </Button>
          </div>
          {error ? (
            <p className="mt-4 text-state-critical text-sm" role="alert">
              {error}
            </p>
          ) : null}
        </section>

        {queue ? (
          <div className="mt-6 grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)] lg:items-start">
            <nav
              className="overflow-hidden rounded-panel border border-border bg-surface"
              aria-label="Submissions"
            >
              {queue.length === 0 ? (
                <p className="p-5 text-muted-foreground text-sm">No submissions in this queue.</p>
              ) : (
                queue.map((submission) => (
                  <button
                    key={submission.id}
                    type="button"
                    onClick={() => {
                      setSelectedId(submission.id);
                      setNote("");
                    }}
                    className={cn(
                      "block w-full border-border border-b p-4 text-left last:border-b-0 hover:bg-interactive",
                      selected?.id === submission.id && "bg-accent-soft",
                    )}
                  >
                    <code className="block truncate font-mono text-accent-ink text-xs">
                      {submission.coordinate}
                    </code>
                    <span className="mt-2 flex items-center justify-between gap-2">
                      <span className="truncate text-muted-foreground text-xs">
                        {submission.contributor.name ?? "Anonymous contributor"}
                      </span>
                      <StatusBadge status={submission.status} />
                    </span>
                  </button>
                ))
              )}
            </nav>
            {selected ? (
              <SubmissionReview
                submission={selected}
                note={note}
                busy={busy}
                onNote={setNote}
                onDecision={(decision) => void decide(decision)}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </>
  );
}

function SubmissionReview({
  submission,
  note,
  busy,
  onNote,
  onDecision,
}: {
  submission: ReviewerSubmission;
  note: string;
  busy: boolean;
  onNote: (value: string) => void;
  onDecision: (decision: "approve" | "reject") => void;
}) {
  const coordinate = Coordinate.parse(submission.coordinate);
  return (
    <article className="min-w-0 space-y-4">
      <section className="rounded-panel border border-border bg-surface p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <code className="break-all font-mono font-semibold text-accent-ink text-sm">
              {submission.coordinate}
            </code>
            <p className="mt-1 text-subtle-foreground text-xs">
              artifacts/{coordinate.manifestPath}
            </p>
          </div>
          <StatusBadge status={submission.status} />
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <Check label="Canonical schema" value="Passed" />
          <Check label="Locator pinning" value="Passed" />
          <Check label="Registry duplicate" value="Checked again on approve" caution />
        </div>
        <dl className="mt-5 grid gap-3 border-border border-t pt-5 text-sm sm:grid-cols-2">
          <Fact label="DOI" value={submission.manifest.doi ?? "Not supplied"} />
          <Fact label="License" value={submission.manifest.license ?? "Not supplied"} />
        </dl>
      </section>

      <section className="rounded-panel border border-border bg-surface p-4 sm:p-5">
        <h2 className="font-display font-semibold text-lg">Sources</h2>
        <p className="mt-1 text-subtle-foreground text-xs">
          Reachability is a reviewer check; MolHub does not proxy arbitrary contributor URLs.
        </p>
        <div className="mt-4 space-y-4">
          {submission.manifest.artifacts.map((artifact) => (
            <div key={artifact.role} className="rounded-control border border-border p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <code className="font-mono font-semibold">{artifact.role}</code>
                {artifact.format ? <Badge tone="neutral">{artifact.format}</Badge> : null}
                <span className="text-muted-foreground">{artifact.filename}</span>
              </div>
              <ul className="mt-2 space-y-1">
                {artifact.locators.map((locator) => (
                  <li key={locator} className="break-all font-mono text-xs">
                    {/^https?:\/\//.test(locator) ? (
                      <a
                        href={locator}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-accent-ink hover:underline"
                      >
                        {locator} <ExternalLink className="size-3" aria-hidden="true" />
                      </a>
                    ) : (
                      locator
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="overflow-hidden rounded-panel border border-border bg-surface">
        <div className="border-border border-b px-4 py-3">
          <h2 className="font-display font-semibold">Canonical manifest</h2>
        </div>
        <pre className="max-h-[30rem] overflow-auto bg-code p-5 text-code-foreground text-xs leading-6">
          <code>{submission.manifestYaml}</code>
        </pre>
      </section>

      {submission.pullRequestUrl ? (
        <a
          href={submission.pullRequestUrl}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 text-accent-ink text-sm hover:underline"
        >
          Open registry pull request <ExternalLink className="size-4" aria-hidden="true" />
        </a>
      ) : null}

      {submission.status === "pending" ? (
        <section className="rounded-panel border border-border bg-canvas-tinted p-4 sm:p-5">
          <label htmlFor="review-note" className="font-medium text-sm">
            Review note
          </label>
          <p className="mt-1 text-subtle-foreground text-xs">
            Required for rejection; included in the submission status.
          </p>
          <Textarea
            id="review-note"
            rows={3}
            value={note}
            onChange={(event) => onNote(event.target.value)}
            className="mt-2"
          />
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <Button disabled={busy} onClick={() => onDecision("approve")}>
              <CheckCircle2 aria-hidden="true" /> Approve and open PR
            </Button>
            <Button
              variant="outline"
              disabled={busy || !note.trim()}
              onClick={() => onDecision("reject")}
            >
              <XCircle aria-hidden="true" /> Reject with note
            </Button>
          </div>
        </section>
      ) : null}
    </article>
  );
}

function Check({
  label,
  value,
  caution = false,
}: { label: string; value: string; caution?: boolean }) {
  return (
    <div className="rounded-control border border-border p-3">
      <p className="text-subtle-foreground text-xs">{label}</p>
      <p
        className={cn(
          "mt-1 font-medium text-sm",
          caution ? "text-state-caution" : "text-state-attested",
        )}
      >
        {value}
      </p>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-subtle-foreground text-xs">{label}</dt>
      <dd className="mt-1 break-all">{value}</dd>
    </div>
  );
}

function StatusBadge({ status }: { status: SubmissionStatus }) {
  const tone = status === "accepted" ? "attested" : status === "rejected" ? "caution" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}

function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "w-full resize-y rounded-control border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
        className,
      )}
      {...props}
    />
  );
}

function messageOf(error: unknown): string {
  if (error instanceof SubmissionApiError || error instanceof Error) return error.message;
  return "Review request failed.";
}
