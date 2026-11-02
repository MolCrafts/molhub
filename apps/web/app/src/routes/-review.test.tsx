import { type ReviewerSubmission, SubmissionClient } from "@/lib/submissions";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReviewPage, SubmissionReview } from "./review";

const submission: ReviewerSubmission = {
  id: "test-id",
  coordinate: "dataset:lab/test@v1",
  status: "reviewing",
  pullRequestUrl: null,
  reviewNote: null,
  contributor: {},
  createdAt: "2026-10-23T00:00:00Z",
  updatedAt: "2026-10-23T00:00:00Z",
  manifestYaml: "kind: dataset",
  manifest: {
    kind: "dataset",
    namespace: "lab",
    name: "test",
    version: "v1",
    title: "Test",
    artifacts: [],
  },
};

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("submission review recovery", () => {
  it("offers retry without rejection after the decision has been recorded", () => {
    const decide = rs.fn();
    render(
      <SubmissionReview
        submission={submission}
        note="note"
        busy={false}
        onNote={() => undefined}
        onDecision={decide}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry publication" }));
    expect(decide).toHaveBeenCalledWith("approve");
    expect(
      (screen.getByRole("button", { name: "Reject with note" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("refreshes the durable status after an approval request fails", async () => {
    rs.spyOn(SubmissionClient.prototype, "reviewQueue")
      .mockResolvedValueOnce([{ ...submission, status: "pending" }])
      .mockResolvedValue([submission]);
    rs.spyOn(SubmissionClient.prototype, "review").mockRejectedValue(
      new Error("Publication failed"),
    );
    render(<ReviewPage />);
    fireEvent.change(screen.getByLabelText("Admin token"), { target: { value: "test-token" } });
    fireEvent.keyDown(screen.getByLabelText("Admin token"), { key: "Enter" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Approve and open PR" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Approve and open PR" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Retry publication" })).toBeTruthy(),
    );
    expect(screen.getByText("Publication failed")).toBeTruthy();
  });
});
