import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  listReplayScreenshots,
  loadReplayScreenshot,
  testExtensionCapabilities,
} from "@/controllers/API/test-extensions";
import type { ScreenshotRead } from "@/types/test-extensions";
import { extensionCaps } from "../TestProposalPanel/test-fixtures";
import ReplayScreenshots from "./screenshots";
import { replayFixture } from "./test-fixtures";

jest.mock("@/controllers/API/test-extensions", () => ({
  listReplayScreenshots: jest.fn(),
  loadReplayScreenshot: jest.fn(),
  testExtensionCapabilities: jest.fn(),
  attachReplayScreenshot: jest.fn(),
}));
const row = replayFixture("READY_FOR_SUBMISSION", "FAIL");
const image: ScreenshotRead = {
  schema_version: "0.1",
  profile_ref: "evidence-profile:supplementary-png/0.1.0",
  attachment_id: "image-one",
  workflow_run_id: row.plan.workflow_run_id,
  plan_id: row.plan.plan_id,
  plan_digest: row.plan_digest,
  execution_id: row.execution_id!,
  candidate_digest: row.plan.candidate.content_digest,
  case_id: "answer",
  caption: "Reference only",
  authority: "SUPPLEMENTARY_UNTRUSTED",
  affects_verdict: false,
  capture_provenance_verified: false,
  uploaded_by: "owner",
  uploaded_at: "2026-10-13T05:00:00Z",
  input_digest: "sha256:" + "8".repeat(64),
  content_digest: "sha256:" + "7".repeat(64),
  media_type: "image/png",
  byte_size: 100,
  width: 20,
  height: 10,
  case_evidence_digest: row.evidence_digest!,
};
beforeEach(() => {
  jest.clearAllMocks();
  URL.createObjectURL = jest.fn(() => "blob:checked-raster");
  URL.revokeObjectURL = jest.fn();
  (listReplayScreenshots as jest.Mock).mockResolvedValue([image]);
  (testExtensionCapabilities as jest.Mock).mockResolvedValue(extensionCaps);
  (loadReplayScreenshot as jest.Mock).mockResolvedValue(
    new Blob([], { type: "image/png" }),
  );
});
const mount = (human = false) =>
  render(
    <ReplayScreenshots row={row} identity="owner/run/plan" human={human} />,
  );
test("native view previews only after authenticated checksum loading, without uploads", async () => {
  const { unmount } = mount();
  expect(listReplayScreenshots).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: /^Load screenshot archive$/i }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /^Preview reference 1$/i }),
  );
  const img = await screen.findByRole("img");
  expect(img).toHaveAttribute("src", "blob:checked-raster");
  expect(loadReplayScreenshot).toHaveBeenCalledWith(row, image);
  expect(
    screen.getByText(/Capture provenance: unverified · no verdict authority/),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Attach supplementary PNG$/i }),
  ).not.toBeInTheDocument();
  unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:checked-raster");
});
test("forged trusted screenshot, foreign execution and arbitrary image URL never load", async () => {
  (listReplayScreenshots as jest.Mock).mockResolvedValue([
    { ...image, affects_verdict: true },
    { ...image, execution_id: "other" },
    {
      ...image,
      media_type: "image/svg+xml",
      url: "https://untrusted/image.svg",
    },
  ]);
  const { container } = mount();
  fireEvent.click(
    screen.getByRole("button", { name: /^Load screenshot archive$/i }),
  );
  expect(
    await screen.findAllByText(/Unsupported screenshot metadata/),
  ).toHaveLength(3);
  expect(container.querySelector("img")).toBeNull();
  expect(loadReplayScreenshot).not.toHaveBeenCalled();
});
test("checksum failure leaves official report unaffected and exposes no image", async () => {
  (loadReplayScreenshot as jest.Mock).mockRejectedValue(
    new Error("bad digest"),
  );
  mount();
  fireEvent.click(
    screen.getByRole("button", { name: /^Load screenshot archive$/i }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /^Preview reference 1$/i }),
  );
  await screen.findByText(/Image checksum or ownership could not be confirmed/);
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
});
test("late binary response after unmount creates no object URL", async () => {
  let resolve!: (v: Blob) => void;
  (loadReplayScreenshot as jest.Mock).mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const { unmount } = mount();
  fireEvent.click(
    screen.getByRole("button", { name: /^Load screenshot archive$/i }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: /^Preview reference 1$/i }),
  );
  await waitFor(() => expect(loadReplayScreenshot).toHaveBeenCalled());
  unmount();
  resolve(new Blob());
  await Promise.resolve();
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
