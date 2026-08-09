import type { ScatterChart } from "@molcrafts/molplot";
import { LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type AxisProperty = "frame" | "energy";

interface PropertyPlotProps {
  energy: Float64Array | null;
  frameCount: number;
  frame: number;
  x: AxisProperty;
  y: AxisProperty;
  color: "none" | "energy";
  onFrameChange: (frame: number) => void;
}

export function PropertyPlot({
  energy,
  frameCount,
  frame,
  x,
  y,
  color,
  onFrameChange,
}: PropertyPlotProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<ScatterChart | null>(null);
  const frameRef = useRef(frame);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !energy || frameCount === 0) return;
    let cancelled = false;
    let dispose: (() => void) | undefined;

    setState("loading");
    void import("@molcrafts/molplot")
      .then(async ({ ScatterChart }) => {
        if (cancelled) return;
        const count = Math.min(frameCount, energy.length);
        const value = (property: AxisProperty, index: number) =>
          property === "frame" ? index : (energy[index] ?? Number.NaN);
        const points = Array.from({ length: count }, (_, index) => ({
          x: value(x, index),
          y: value(y, index),
          customdata: { frame: index },
        }));
        const chart = new ScatterChart(container, {
          points,
          xAxis: { label: x === "frame" ? "Frame" : "Energy (eV)" },
          yAxis: { label: y === "frame" ? "Frame" : "Energy (eV)" },
          marker: {
            size: 6,
            color: color === "energy" ? Array.from(energy.slice(0, count)) : undefined,
            colorscale: "viridis",
            showscale: color === "energy",
          },
          highlight: { index: 0 },
          theme: "auto",
          preset: "molplot",
          hovertemplate: ".4f",
        });
        chartRef.current = chart;
        const offClick = chart.onPointClick((point) => {
          const selected = point.customdata as { frame?: unknown } | undefined;
          if (typeof selected?.frame === "number") onFrameChange(selected.frame);
        });
        await chart.ready();
        if (cancelled) {
          offClick();
          chart.dispose();
          return;
        }
        await chart.setHighlight(Math.min(frameRef.current, count - 1));
        setState("ready");
        dispose = () => {
          chartRef.current = null;
          offClick();
          chart.dispose();
        };
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });

    return () => {
      cancelled = true;
      dispose?.();
    };
  }, [color, energy, frameCount, onFrameChange, x, y]);

  useEffect(() => {
    frameRef.current = frame;
    void chartRef.current?.setHighlight(frame);
    containerRef.current?.setAttribute("data-active-frame", String(frame));
  }, [frame]);

  if (!energy && frameCount > 0) {
    return (
      <div className="grid min-h-80 place-items-center rounded-panel border border-border bg-surface p-6 text-center">
        <div>
          <p className="font-medium">No structure-level energy column</p>
          <p className="mt-1 text-muted-foreground text-sm">
            The trajectory is viewable, but this role does not expose energy as a numeric frame
            property.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative min-h-80 min-w-0 max-w-full overflow-hidden rounded-panel border border-border bg-surface p-3">
      <div ref={containerRef} className="h-80 w-full" aria-label={`${x} by ${y} property map`} />
      {state === "loading" ? (
        <div className="absolute inset-0 grid place-items-center bg-surface/90" aria-live="polite">
          <div className="text-center text-muted-foreground text-sm">
            <LoaderCircle className="mx-auto size-5 animate-spin" aria-hidden="true" />
            <span className="mt-2 block">Preparing property map…</span>
          </div>
        </div>
      ) : null}
      {state === "error" ? (
        <div
          className="absolute inset-0 grid place-items-center bg-surface p-6 text-center"
          role="alert"
        >
          <p className="text-state-critical text-sm">The property map could not be rendered.</p>
        </div>
      ) : null}
      <p className="mt-2 text-center text-muted-foreground text-xs">
        Active point: frame <span className="font-mono text-foreground">{frame}</span>
      </p>
    </div>
  );
}
