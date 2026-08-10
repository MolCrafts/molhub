import { describe, expect, it } from "@rstest/core";

import { boundedFrame, classifyInspectorError, inspectorSearchSchema } from "@/lib/inspector-state";

describe("Inspector URL state", () => {
  it("restores valid share state and replaces malformed values with safe defaults", () => {
    expect(
      inspectorSearchSchema.parse({
        role: "train_300K",
        frame: "42",
        x: "energy",
        y: "frame",
        color: "energy",
      }),
    ).toEqual({
      role: "train_300K",
      frame: 42,
      x: "energy",
      y: "frame",
      color: "energy",
    });

    expect(inspectorSearchSchema.parse({ frame: "nope", x: "filename" })).toMatchObject({
      frame: 0,
      x: "frame",
      y: "energy",
      color: "none",
    });
  });

  it("bounds frame indices after trajectory metadata arrives", () => {
    expect(boundedFrame(42, 10)).toBe(9);
    expect(boundedFrame(-2, 10)).toBe(0);
  });

  it("classifies actionable remote errors", () => {
    expect(classifyInspectorError("blocked by CORS policy")).toBe("cors");
    expect(classifyInspectorError("Failed to fetch")).toBe("network");
    expect(classifyInspectorError("XYZ reader parse error")).toBe("parse");
  });
});
