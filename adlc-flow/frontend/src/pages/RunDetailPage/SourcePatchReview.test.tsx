import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  getAdlcHarnessSourcePatchPreview,
  getAdlcSourcePatch,
} from "@/controllers/API/adlc";
import type {
  AdlcArtifact,
  AdlcHarnessRunSession,
  AdlcTaskRun,
} from "@/types/adlc";
import SourcePatchReview, {
  capturedSourcePatches,
  sourcePatchReviewKey,
} from "./SourcePatchReview";

jest.mock("@/controllers/API/adlc", () => ({
  getAdlcSourcePatch: jest.fn(),
  getAdlcHarnessSourcePatchPreview: jest.fn(),
}));

const mockGetSourcePatch = getAdlcSourcePatch as jest.MockedFunction<
  typeof getAdlcSourcePatch
>;

const artifact: AdlcArtifact = {
  artifact_id: "artifact-1",
  workflow_run_id: "run-1",
  task_run_id: "task-1",
  kind: "SOURCE_PATCH",
  name: "source-patch.json",
  media_type: "application/vnd.opencode.vcs-diff+json",
  uri: "adlc://runs/run-1/artifacts/artifact-1",
  size_bytes: 100,
  checksum: { algorithm: "SHA256", value: "abc123" },
  metadata: { capture: "workspace-vcs-diff", payload_retained: true },
};

const task: AdlcTaskRun = {
  id: "task-1",
  workflow_run_id: "run-1",
  key: "implement",
  name: "Implement Backend",
  task_type: "coding",
  status: "SUCCEEDED",
  dependency_task_run_ids: [],
  retry_count: 0,
  artifacts: [artifact],
};

const harnessArtifact: AdlcArtifact = {
  ...artifact,
  artifact_id: "harness-patch",
  attempt_id: "attempt-1",
  metadata: { capture: "harness-git-diff" },
};
const previewSession = {
  task_run_id: task.id,
  attempt_id: "attempt-1",
  session: {
    session_id: "session-1",
    result: { artifacts: [harnessArtifact] },
  },
} as AdlcHarnessRunSession;
const harnessPatch = {
  artifact: harnessArtifact,
  format: "harness-git-diff-v1" as const,
  base_commit: "a".repeat(40),
  files: [
    {
      file: "README.md",
      patch: "diff --git a/README.md b/README.md\n+actual edit\n",
      additions: 1,
      deletions: 0,
    },
  ],
  reported_files: ["README.md"],
};

describe("SourcePatchReview", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("reviews a prepared Harness patch and distinguishes the saved state", async () => {
    (getAdlcHarnessSourcePatchPreview as jest.Mock).mockResolvedValue(
      harnessPatch,
    );
    const availability = jest.fn();
    const previewAvailability = jest.fn();
    const { rerender } = render(
      <SourcePatchReview
        runId="run-1"
        tasks={[{ ...task, artifacts: [] }]}
        sessions={[previewSession]}
        onAvailabilityChange={availability}
        onPreviewAvailabilityChange={previewAvailability}
      />,
    );
    expect(await screen.findByText("Preview — not submitted")).toBeVisible();
    expect(getAdlcHarnessSourcePatchPreview).toHaveBeenCalledWith(
      "run-1",
      "session-1",
      "harness-patch",
    );
    expect(mockGetSourcePatch).not.toHaveBeenCalled();
    expect(previewAvailability).toHaveBeenLastCalledWith(["session-1"]);
    mockGetSourcePatch.mockResolvedValue(harnessPatch);
    rerender(
      <SourcePatchReview
        runId="run-1"
        tasks={[{ ...task, artifacts: [harnessArtifact] }]}
        sessions={[previewSession]}
        onAvailabilityChange={availability}
        onPreviewAvailabilityChange={previewAvailability}
      />,
    );
    expect(await screen.findByText("Saved artifact")).toBeVisible();
    expect(mockGetSourcePatch).toHaveBeenCalledWith("run-1", "harness-patch");
    expect(
      screen.queryByText("Preview — not submitted"),
    ).not.toBeInTheDocument();
  });

  it("downloads only the reviewed diff without an execution command", async () => {
    mockGetSourcePatch.mockResolvedValue(harnessPatch);
    const createUrl = jest.fn(() => "blob:reviewed-patch");
    const revokeUrl = jest.fn();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeUrl,
    });
    const click = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    render(
      <SourcePatchReview
        runId="run-1"
        tasks={[{ ...task, artifacts: [harnessArtifact] }]}
        onAvailabilityChange={jest.fn()}
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Download patch" }),
    );
    expect(createUrl).toHaveBeenCalledWith(expect.any(Blob));
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeUrl).toHaveBeenCalledWith("blob:reviewed-patch");
    click.mockRestore();
  });

  it("does not refetch an unchanged patch on every run poll", async () => {
    mockGetSourcePatch.mockResolvedValue(harnessPatch);
    const availability = jest.fn();
    const { rerender } = render(
      <SourcePatchReview
        runId="run-1"
        tasks={[{ ...task, artifacts: [harnessArtifact] }]}
        onAvailabilityChange={availability}
      />,
    );
    await screen.findByText("Saved artifact");
    rerender(
      <SourcePatchReview
        runId="run-1"
        tasks={[{ ...task, artifacts: [{ ...harnessArtifact }] }]}
        onAvailabilityChange={availability}
      />,
    );
    expect(mockGetSourcePatch).toHaveBeenCalledTimes(1);
  });

  it("never makes a failed preview available for Submit", async () => {
    (getAdlcHarnessSourcePatchPreview as jest.Mock).mockRejectedValue(
      new Error("Checksum mismatch"),
    );
    const previewAvailability = jest.fn();
    render(
      <SourcePatchReview
        runId="run-1"
        tasks={[{ ...task, artifacts: [] }]}
        sessions={[previewSession]}
        onAvailabilityChange={jest.fn()}
        onPreviewAvailabilityChange={previewAvailability}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Checksum mismatch",
    );
    expect(previewAvailability).toHaveBeenLastCalledWith([]);
    expect(
      screen.queryByRole("button", { name: "Download patch" }),
    ).not.toBeInTheDocument();
  });

  it("loads a patch as plain text and enables review only after it is available", async () => {
    mockGetSourcePatch.mockResolvedValue({
      artifact,
      format: "opencode-vcs-diff-v1",
      files: [
        {
          file: "README.md",
          patch: "--- a/README.md\n+++ b/README.md\n+<script>alert(1)</script>",
          additions: 1,
          deletions: 0,
        },
      ],
      reported_files: ["README.md"],
    });
    const availability = jest.fn();

    const { container } = render(
      <SourcePatchReview
        runId="run-1"
        tasks={[task]}
        onAvailabilityChange={availability}
      />,
    );

    expect(mockGetSourcePatch).toHaveBeenCalledWith("run-1", "artifact-1");
    expect(
      await screen.findByText(/<script>alert\(1\)<\/script>/),
    ).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    await waitFor(() =>
      expect(availability).toHaveBeenLastCalledWith("run-1:artifact-1"),
    );
  });

  it("keeps approval unavailable when a patch cannot be loaded", async () => {
    mockGetSourcePatch.mockRejectedValue(new Error("Patch expired"));
    const availability = jest.fn();

    render(
      <SourcePatchReview
        runId="run-1"
        tasks={[task]}
        onAvailabilityChange={availability}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Patch expired");
    expect(availability).toHaveBeenLastCalledWith(undefined);
  });

  it("ties review readiness to the run and exact artifact set", () => {
    const candidates = capturedSourcePatches([task]);

    expect(sourcePatchReviewKey("run-1", candidates)).toBe("run-1:artifact-1");
    expect(sourcePatchReviewKey("run-2", candidates)).not.toBe(
      sourcePatchReviewKey("run-1", candidates),
    );
    expect(sourcePatchReviewKey("run-1", [])).not.toBe(
      sourcePatchReviewKey("run-1", candidates),
    );
  });

  it("invalidates readiness and removes stale content at retention expiry", async () => {
    jest.useFakeTimers();
    try {
      jest.setSystemTime(new Date("2026-10-18T00:00:00Z"));
      mockGetSourcePatch.mockResolvedValueOnce({
        ...harnessPatch,
        artifact: { ...harnessArtifact, expires_at: "2026-10-18T00:00:01Z" },
      }).mockRejectedValue(new Error("Patch expired"));
      const availability = jest.fn();
      render(<SourcePatchReview runId="run-1" tasks={[{ ...task, artifacts: [harnessArtifact] }]} onAvailabilityChange={availability} />);
      await act(async () => { await Promise.resolve(); });
      expect(availability).toHaveBeenLastCalledWith("run-1:harness-patch");
      await act(async () => { jest.advanceTimersByTime(1001); });
      expect(availability).toHaveBeenLastCalledWith(undefined);
      expect(screen.getByRole("alert")).toHaveTextContent("Patch expired");
      expect(screen.queryByText(/actual edit/)).toBeNull();
    } finally { jest.useRealTimers(); }
  });
});
