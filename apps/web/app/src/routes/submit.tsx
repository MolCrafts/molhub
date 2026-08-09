import { createFileRoute } from "@tanstack/react-router";
import {
  CheckCircle2,
  Download,
  FileCheck2,
  Plus,
  Send,
  Trash2,
  TriangleAlert,
} from "lucide-react";
import {
  type ChangeEvent,
  type ComponentProps,
  type FormEvent,
  type ReactNode,
  useMemo,
  useState,
} from "react";

import { CopyButton } from "@/components/snippets";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type ArtifactDraft,
  DEFAULT_MANIFEST_DRAFT,
  type ManifestDraft,
  buildManifestDocument,
  buildManifestYaml,
  createArtifactDraft,
  manifestCoordinate,
  validateManifestDraft,
} from "@/lib/manifest-builder";
import { SubmissionApiError, SubmissionClient, type SubmissionReceipt } from "@/lib/submissions";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/submit")({
  head: () => ({
    meta: [
      { title: "Create a manifest — MolHub" },
      {
        name: "description",
        content: "Create and validate a MolHub manifest in the browser.",
      },
    ],
  }),
  component: SubmitPage,
});

function SubmitPage() {
  const [draft, setDraft] = useState<ManifestDraft>(DEFAULT_MANIFEST_DRAFT);
  const [contributorEmail, setContributorEmail] = useState("");
  const [receipt, setReceipt] = useState<SubmissionReceipt | null>(null);
  const [submissionError, setSubmissionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const yaml = useMemo(() => buildManifestYaml(draft), [draft]);
  const errors = useMemo(() => validateManifestDraft(draft), [draft]);
  const coordinate = manifestCoordinate(draft);

  function update(event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) {
    const key = event.target.name as Exclude<keyof ManifestDraft, "artifacts">;
    setDraft((current) => ({ ...current, [key]: event.target.value }));
  }

  function updateArtifact(
    id: string,
    key: Exclude<keyof ArtifactDraft, "id" | "locators">,
    value: string,
  ) {
    setDraft((current) => ({
      ...current,
      artifacts: current.artifacts.map((artifact) =>
        artifact.id === id ? { ...artifact, [key]: value } : artifact,
      ),
    }));
  }

  function updateLocator(id: string, locatorIndex: number, value: string) {
    setDraft((current) => ({
      ...current,
      artifacts: current.artifacts.map((artifact) =>
        artifact.id === id
          ? {
              ...artifact,
              locators: artifact.locators.map((locator, index) =>
                index === locatorIndex ? value : locator,
              ),
            }
          : artifact,
      ),
    }));
  }

  function addLocator(id: string) {
    setDraft((current) => ({
      ...current,
      artifacts: current.artifacts.map((artifact) =>
        artifact.id === id ? { ...artifact, locators: [...artifact.locators, ""] } : artifact,
      ),
    }));
  }

  function removeLocator(id: string, locatorIndex: number) {
    setDraft((current) => ({
      ...current,
      artifacts: current.artifacts.map((artifact) =>
        artifact.id === id
          ? {
              ...artifact,
              locators: artifact.locators.filter((_, index) => index !== locatorIndex),
            }
          : artifact,
      ),
    }));
  }

  function addArtifact() {
    setDraft((current) => ({
      ...current,
      artifacts: [...current.artifacts, createArtifactDraft()],
    }));
  }

  function removeArtifact(id: string) {
    setDraft((current) => ({
      ...current,
      artifacts: current.artifacts.filter((artifact) => artifact.id !== id),
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (errors.length > 0 || submitting) return;
    setSubmitting(true);
    setSubmissionError(null);
    setReceipt(null);
    try {
      const created = await new SubmissionClient().submit(buildManifestDocument(draft), {
        ...(contributorEmail.trim() ? { email: contributorEmail.trim() } : {}),
      });
      setReceipt(created);
    } catch (error) {
      if (error instanceof SubmissionApiError && error.issues.length > 0) {
        setSubmissionError(error.issues.map((issue) => issue.message).join(" "));
      } else {
        setSubmissionError(error instanceof Error ? error.message : "Submission failed.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function download() {
    const blob = new Blob([yaml], { type: "application/yaml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${draft.name.trim() || "molhub"}-${draft.version.trim() || "manifest"}.yaml`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      <section className="mesh-background border-border border-b">
        <div className="page-shell py-8 sm:py-10">
          <h1 className="font-display font-bold text-3xl tracking-tight sm:text-4xl">
            Submit a manifest
          </h1>
          <p className="mt-2 text-muted-foreground">
            Describe the artifact and send it for review.
          </p>
        </div>
      </section>

      <div className="page-shell grid gap-6 py-8 lg:grid-cols-[minmax(0,1fr)_minmax(24rem,0.9fr)] lg:items-start lg:py-10">
        <form id="manifest-form" className="min-w-0 space-y-4" onSubmit={submit}>
          <FormSection number="01" title="Identity">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Kind" htmlFor="kind">
                <Select id="kind" name="kind" value={draft.kind} onChange={update}>
                  <option value="dataset">Dataset</option>
                  <option value="model">Model</option>
                  <option value="plugin">Plugin</option>
                </Select>
              </Field>
              <Field
                label="Namespace"
                htmlFor="namespace"
                hint="Lowercase lab or organization slug"
              >
                <Input id="namespace" name="namespace" value={draft.namespace} onChange={update} />
              </Field>
              <Field label="Name" htmlFor="name">
                <Input id="name" name="name" value={draft.name} onChange={update} />
              </Field>
              <Field label="Version" htmlFor="version" hint="A fixed release, never latest">
                <Input id="version" name="version" value={draft.version} onChange={update} />
              </Field>
            </div>
            <div className="mt-4 rounded-control border border-accent-line bg-accent-soft p-3">
              <p className="text-subtle-foreground text-xs">Coordinate preview</p>
              <code className="mt-1 block overflow-x-auto font-mono font-medium text-accent-ink text-sm">
                {coordinate}
              </code>
            </div>
          </FormSection>

          <FormSection number="02" title="Description">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Title" htmlFor="title" className="sm:col-span-2">
                <Input id="title" name="title" value={draft.title} onChange={update} />
              </Field>
              <Field label="Description" htmlFor="description" className="sm:col-span-2">
                <Textarea
                  id="description"
                  name="description"
                  value={draft.description}
                  onChange={update}
                  rows={3}
                />
              </Field>
              <Field label="SPDX license" htmlFor="license" hint="For example CC0-1.0 or MIT">
                <Input id="license" name="license" value={draft.license} onChange={update} />
              </Field>
              <Field label="DOI" htmlFor="doi" hint="Required for the published version">
                <Input id="doi" name="doi" value={draft.doi} onChange={update} />
              </Field>
            </div>
          </FormSection>

          <FormSection number="03" title="Files">
            <div className="space-y-4">
              {draft.artifacts.map((artifact, artifactIndex) => (
                <div
                  key={artifact.id}
                  className="rounded-control border border-border bg-canvas-tinted p-4"
                >
                  <div className="mb-4 flex items-center justify-between gap-3">
                    <h3 className="font-display font-semibold">File {artifactIndex + 1}</h3>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      disabled={draft.artifacts.length === 1}
                      onClick={() => removeArtifact(artifact.id)}
                      aria-label={`Remove file ${artifactIndex + 1}`}
                    >
                      <Trash2 aria-hidden="true" /> Remove
                    </Button>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <Field label="Role" htmlFor={`${artifact.id}-role`}>
                      <Input
                        id={`${artifact.id}-role`}
                        value={artifact.role}
                        onChange={(event) =>
                          updateArtifact(artifact.id, "role", event.target.value)
                        }
                      />
                    </Field>
                    <Field label="Filename" htmlFor={`${artifact.id}-filename`}>
                      <Input
                        id={`${artifact.id}-filename`}
                        value={artifact.filename}
                        onChange={(event) =>
                          updateArtifact(artifact.id, "filename", event.target.value)
                        }
                      />
                    </Field>
                    <Field
                      label="Format"
                      htmlFor={`${artifact.id}-format`}
                      hint="extxyz, npz, csv…"
                    >
                      <Input
                        id={`${artifact.id}-format`}
                        value={artifact.format}
                        onChange={(event) =>
                          updateArtifact(artifact.id, "format", event.target.value)
                        }
                      />
                    </Field>
                    <Field label="Media type" htmlFor={`${artifact.id}-media-type`}>
                      <Input
                        id={`${artifact.id}-media-type`}
                        value={artifact.mediaType}
                        onChange={(event) =>
                          updateArtifact(artifact.id, "mediaType", event.target.value)
                        }
                      />
                    </Field>
                    <div className="space-y-3 sm:col-span-2">
                      <div className="flex items-end justify-between gap-3">
                        <div>
                          <p className="font-medium text-sm">Locators</p>
                          <p className="text-subtle-foreground text-xs">
                            Ordered fallbacks; pin every version or commit.
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => addLocator(artifact.id)}
                        >
                          <Plus aria-hidden="true" /> Add locator
                        </Button>
                      </div>
                      {artifact.locators.map((locator, locatorIndex) => (
                        <div key={`${artifact.id}-locator-${locatorIndex}`} className="flex gap-2">
                          <Input
                            aria-label={`File ${artifactIndex + 1} locator ${locatorIndex + 1}`}
                            value={locator}
                            onChange={(event) =>
                              updateLocator(artifact.id, locatorIndex, event.target.value)
                            }
                          />
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            disabled={artifact.locators.length === 1}
                            onClick={() => removeLocator(artifact.id, locatorIndex)}
                            aria-label={`Remove locator ${locatorIndex + 1}`}
                          >
                            <Trash2 aria-hidden="true" />
                          </Button>
                        </div>
                      ))}
                    </div>
                    <Field
                      label="Size in bytes"
                      htmlFor={`${artifact.id}-size`}
                      hint="Required when no digest is published"
                    >
                      <Input
                        id={`${artifact.id}-size`}
                        inputMode="numeric"
                        value={artifact.size}
                        onChange={(event) =>
                          updateArtifact(artifact.id, "size", event.target.value)
                        }
                      />
                    </Field>
                    <Field
                      label="Published digest"
                      htmlFor={`${artifact.id}-digest`}
                      hint="Optional: md5:… or sha256:…"
                    >
                      <Input
                        id={`${artifact.id}-digest`}
                        value={artifact.digest}
                        onChange={(event) =>
                          updateArtifact(artifact.id, "digest", event.target.value)
                        }
                      />
                    </Field>
                  </div>
                </div>
              ))}
              <Button type="button" variant="outline" onClick={addArtifact}>
                <Plus aria-hidden="true" /> Add file
              </Button>
            </div>
          </FormSection>

          <FormSection number="04" title="Scientific targets">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Graph-level" htmlFor="graphTargets" hint="energy, dipole, band_gap">
                <Input
                  id="graphTargets"
                  name="graphTargets"
                  value={draft.graphTargets}
                  onChange={update}
                />
              </Field>
              <Field label="Atom-level" htmlFor="atomTargets" hint="forces, charges">
                <Input
                  id="atomTargets"
                  name="atomTargets"
                  value={draft.atomTargets}
                  onChange={update}
                />
              </Field>
            </div>
          </FormSection>
        </form>

        <aside className="min-w-0 space-y-4 lg:sticky lg:top-24">
          <div className="overflow-hidden rounded-panel border border-border bg-surface shadow-raised">
            <div className="flex flex-wrap items-center justify-between gap-3 border-border border-b px-4 py-3">
              <div className="flex items-center gap-2">
                <FileCheck2 className="size-4 text-accent-ink" aria-hidden="true" />
                <h2 className="font-display font-semibold">manifest.yaml</h2>
              </div>
              {errors.length === 0 ? (
                <Badge tone="attested">
                  <CheckCircle2 /> Ready
                </Badge>
              ) : (
                <Badge tone="caution">
                  <TriangleAlert /> {errors.length} issue{errors.length === 1 ? "" : "s"}
                </Badge>
              )}
            </div>
            <pre className="max-h-[34rem] overflow-auto bg-code p-5 text-code-foreground text-xs leading-6">
              <code>{yaml}</code>
            </pre>
            <div className="flex flex-col gap-2 border-border border-t p-4 sm:flex-row">
              <Button
                type="button"
                onClick={download}
                disabled={errors.length > 0}
                className="flex-1"
              >
                <Download aria-hidden="true" /> Download YAML
              </Button>
              <CopyButton text={yaml} subject="the generated manifest" />
            </div>
          </div>

          {errors.length > 0 ? (
            <div className="rounded-panel border border-state-caution-line bg-state-caution-soft p-4">
              <h2 className="flex items-center gap-2 font-semibold text-sm">
                <TriangleAlert className="size-4 text-state-caution" aria-hidden="true" /> Fix
                before download
              </h2>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground text-sm">
                {errors.map((error) => (
                  <li key={`${error.path}:${error.code}:${error.message}`}>
                    <code className="font-mono text-xs">{error.path}</code> {error.message}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="rounded-panel border border-border bg-canvas-tinted p-4">
            <Send className="size-5 text-accent-ink" aria-hidden="true" />
            <h2 className="mt-3 font-display font-semibold">Send for review</h2>
            <Field
              label="Email"
              htmlFor="contributor-email"
              hint="Optional; used only for review updates"
            >
              <Input
                id="contributor-email"
                type="email"
                value={contributorEmail}
                onChange={(event) => setContributorEmail(event.target.value)}
              />
            </Field>
            <Button
              type="submit"
              form="manifest-form"
              className="mt-4 w-full"
              disabled={errors.length > 0 || submitting}
            >
              <Send aria-hidden="true" /> {submitting ? "Sending…" : "Submit manifest"}
            </Button>
            {receipt ? (
              <div className="mt-4 rounded-control border border-state-attested-line bg-state-attested-soft p-3 text-sm">
                <p className="font-semibold">Submitted</p>
                <p className="mt-1 text-muted-foreground">
                  ID <code className="font-mono">{receipt.id}</code>
                </p>
                <p className="mt-1 capitalize text-muted-foreground">Status: {receipt.status}</p>
              </div>
            ) : null}
            {submissionError ? (
              <p className="mt-4 text-state-critical text-sm" role="alert">
                {submissionError}
              </p>
            ) : null}
          </div>
        </aside>
      </div>
    </>
  );
}

function FormSection({
  number,
  title,
  children,
}: { number: string; title: string; children: ReactNode }) {
  return (
    <fieldset className="rounded-panel border border-border bg-surface p-4 sm:p-5">
      <legend className="sr-only">{title}</legend>
      <div className="mb-4 flex gap-3 border-border border-b pb-4">
        <span className="font-mono text-accent-ink text-xs">{number}</span>
        <h2 className="font-display font-semibold text-lg tracking-tight">{title}</h2>
      </div>
      {children}
    </fieldset>
  );
}

function Field({
  label,
  htmlFor,
  hint,
  className,
  children,
}: { label: string; htmlFor: string; hint?: string; className?: string; children: ReactNode }) {
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={htmlFor} className="font-medium text-sm">
        {label}
      </label>
      {hint ? <p className="mt-0.5 text-subtle-foreground text-xs">{hint}</p> : null}
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

function Select({ className, ...props }: ComponentProps<"select">) {
  return (
    <select
      className={cn(
        "h-control w-full rounded-control border border-input bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring/60",
        className,
      )}
      {...props}
    />
  );
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
