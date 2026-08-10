import { describe, expect, it } from "@rstest/core";

import { Coordinate, InvalidCoordinate } from "../src/index.js";

describe("Coordinate", () => {
  it("normalizes full and shorthand coordinates", () => {
    expect(Coordinate.parse("example@v1").canonical).toBe("dataset:molcrafts/example@v1");
    expect(Coordinate.parse("model:lab/model@1.2").cachePath).toBe("model/lab/model@1.2");
  });

  it("rejects unversioned coordinates", () => {
    expect(() => Coordinate.parse("example")).toThrow(InvalidCoordinate);
  });
});
