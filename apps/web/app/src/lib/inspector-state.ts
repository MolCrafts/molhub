import { z } from "zod";

export const inspectorSearchSchema = z.object({
  role: z.string().min(1).optional().catch(undefined),
  frame: z.coerce.number().int().nonnegative().catch(0).default(0),
  x: z.enum(["frame", "energy"]).catch("frame").default("frame"),
  y: z.enum(["frame", "energy"]).catch("energy").default("energy"),
  color: z.enum(["none", "energy"]).catch("none").default("none"),
  selection: z.string().max(512).optional().catch(undefined),
});

export type InspectorSearch = z.infer<typeof inspectorSearchSchema>;

export function boundedFrame(frame: number, frameCount: number): number {
  if (frameCount <= 0) return 0;
  return Math.min(Math.max(Math.trunc(frame), 0), frameCount - 1);
}

export type InspectorErrorKind = "cors" | "network" | "parse" | "unknown";

export function classifyInspectorError(message: string): InspectorErrorKind {
  const normalized = message.toLowerCase();
  if (normalized.includes("cors") || normalized.includes("cross-origin")) return "cors";
  if (
    normalized.includes("fetch") ||
    normalized.includes("network") ||
    normalized.includes("failed to load")
  )
    return "network";
  if (
    normalized.includes("parse") ||
    normalized.includes("reader") ||
    normalized.includes("invalid") ||
    normalized.includes("unexpected")
  )
    return "parse";
  return "unknown";
}
