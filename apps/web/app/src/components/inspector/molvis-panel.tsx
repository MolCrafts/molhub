import type { Molvis, MolvisViewerElement } from "@molcrafts/molvis-stage";
import { LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { normalizeExtxyzForMolvis, readBoundedText } from "@/lib/extxyz-compat";
import type { MolvisFormat } from "@/lib/inspectability";
import { classifyInspectorError } from "@/lib/inspector-state";

export interface TrajectoryMetadata {
  frameCount: number;
  labels: Map<string, Float64Array>;
  selectedAtoms: number;
  omittedFields: readonly string[];
}

interface MolvisPanelProps {
  source: string;
  size: number | null;
  format: MolvisFormat;
  frame: number;
  onFrameChange: (frame: number) => void;
  onMetadata: (metadata: TrajectoryMetadata) => void;
}

export function MolvisPanel({
  source,
  size,
  format,
  frame,
  onFrameChange,
  onMetadata,
}: MolvisPanelProps) {
  const elementRef = useRef<MolvisViewerElement | null>(null);
  const appRef = useRef<Molvis | null>(null);
  const frameRef = useRef(frame);
  const [preparedSource, setPreparedSource] = useState<{
    url: string;
    omittedFields: readonly string[];
    labels: Map<string, Float64Array>;
  } | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setPreparedSource(null);
    setState("loading");
    setError(null);

    if (format !== "xyz") {
      setPreparedSource({ url: source, omittedFields: [], labels: new Map() });
      return () => controller.abort();
    }

    const maxBytes = 16 * 1024 * 1024;
    if (size !== null && size > maxBytes) {
      setState("error");
      setError(
        "This eager trajectory is larger than the 16 MiB browser limit. Publish a derived inspection record.",
      );
      return () => controller.abort();
    }

    void fetch(source, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`The source returned HTTP ${response.status}.`);
        const content = await readBoundedText(response, maxBytes);
        const normalized = normalizeExtxyzForMolvis(content);
        objectUrl = URL.createObjectURL(new Blob([normalized.content], { type: "chemical/x-xyz" }));
        setPreparedSource({
          url: objectUrl,
          omittedFields: normalized.omittedFields,
          labels: new Map(normalized.numericLabels),
        });
      })
      .catch((value: unknown) => {
        if (controller.signal.aborted) return;
        setError(value instanceof Error ? value.message : String(value));
        setState("error");
      });

    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [format, size, source]);

  useEffect(() => {
    if (!preparedSource) return;
    const element = elementRef.current;
    if (!element) return;
    let cancelled = false;
    const cleanups: Array<() => void> = [];

    setState("loading");
    setError(null);

    const handleReady = (event: Event) => {
      if (cancelled) return;
      const app = (event as CustomEvent<{ app: Molvis }>).detail.app;
      appRef.current = app;

      const publishMetadata = (selectedAtoms = 0) => {
        onMetadata({
          frameCount: app.system.trajectory.length,
          labels: app.system.frameLabels ?? preparedSource.labels,
          selectedAtoms,
          omittedFields: preparedSource.omittedFields,
        });
      };

      cleanups.push(
        app.events.on("frame-change", (nextFrame) => onFrameChange(nextFrame)),
        app.events.on("frame-labels-change", () => publishMetadata()),
        app.events.on("pending-selection-change", ({ atomCount }) => {
          publishMetadata(atomCount);
        }),
      );
      publishMetadata();
      void app.system.seekFrame(frameRef.current);
      setState("ready");
    };

    const handleError = (event: Event) => {
      if (cancelled) return;
      const value = (event as CustomEvent<{ error: Error }>).detail.error;
      setError(value.message);
      setState("error");
    };

    element.addEventListener("molvis:ready", handleReady);
    element.addEventListener("molvis:error", handleError);

    void import("@molcrafts/molvis-stage/element")
      .then(({ defineMolvisViewer }) => {
        if (!cancelled) defineMolvisViewer();
      })
      .catch((value: unknown) => {
        if (cancelled) return;
        setError(value instanceof Error ? value.message : String(value));
        setState("error");
      });

    return () => {
      cancelled = true;
      appRef.current = null;
      element.removeEventListener("molvis:ready", handleReady);
      element.removeEventListener("molvis:error", handleError);
      for (const cleanup of cleanups) cleanup();
    };
  }, [onFrameChange, onMetadata, preparedSource]);

  useEffect(() => {
    frameRef.current = frame;
    const app = appRef.current;
    if (app && app.system.trajectory.currentIndex !== frame) void app.system.seekFrame(frame);
  }, [frame]);

  const errorKind = error ? classifyInspectorError(error) : null;

  return (
    <section
      className="relative min-h-[28rem] min-w-0 max-w-full overflow-hidden rounded-panel border border-border bg-surface-strong"
      aria-label="Molecular structure viewer"
    >
      {preparedSource ? (
        <molvis-viewer
          ref={elementRef}
          src={preparedSource.url}
          format={format}
          controls="view trajectory mode info context-menu"
          modes="view select measure"
          mode="view"
          representation="ball-and-stick"
          background="#101811"
          width="100%"
          height="480px"
        />
      ) : null}

      {state === "loading" ? (
        <div
          className="absolute inset-0 grid place-items-center bg-surface-strong/92 text-[var(--molcrafts-cream)]"
          aria-live="polite"
        >
          <div className="text-center">
            <LoaderCircle className="mx-auto size-6 animate-spin" aria-hidden="true" />
            <p className="mt-3 font-medium text-sm">Loading and indexing trajectory…</p>
            <p className="mt-1 text-white/55 text-xs">Changing role cancels this load.</p>
          </div>
        </div>
      ) : null}

      {state === "error" ? (
        <div className="absolute inset-0 grid place-items-center bg-surface p-6 text-foreground">
          <div className="max-w-md text-center" role="alert">
            <TriangleAlert className="mx-auto size-6 text-state-critical" aria-hidden="true" />
            <h2 className="mt-3 font-display font-semibold text-xl">
              {errorKind === "cors"
                ? "The source blocks browser access"
                : errorKind === "parse"
                  ? "MolVis could not parse this record"
                  : "The trajectory could not be loaded"}
            </h2>
            <p className="mt-2 break-words text-muted-foreground text-sm">{error}</p>
            <Button className="mt-4" variant="outline" onClick={() => window.location.reload()}>
              <RotateCcw aria-hidden="true" /> Retry
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
