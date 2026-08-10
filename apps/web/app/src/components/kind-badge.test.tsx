import { describe, expect, it } from "@rstest/core";
import { render, screen } from "@testing-library/react";

import { KindBadge } from "@/components/kind-badge";

describe("KindBadge", () => {
  it("exposes the artifact kind as text", () => {
    render(<KindBadge kind="model" />);

    expect(screen.getByText("model")).toBeTruthy();
  });
});
