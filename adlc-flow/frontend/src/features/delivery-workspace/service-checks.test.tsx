import "@testing-library/jest-dom";
import { fireEvent, render, screen } from "@testing-library/react";
import type { VaiChecks } from "@/controllers/API/vai-services";
import { ServicesView } from "./service-checks";

const data: VaiChecks = {
  capabilities: {
    version: "0.1.0",
    services: Object.fromEntries(
      ["sandbox", "memory", "testforge"].map((service) => [
        service,
        { available: true, missing_tools: [] },
      ]),
    ),
    allowed_targets: [],
  },
  error_code: null,
  verification_evidence: false,
  checks: [],
};
const base = {
  data,
  loading: false,
  failed: false,
  busy: [],
  canWrite: true,
  error: "",
  onStart: jest.fn(),
  onRefresh: jest.fn(),
};
test("three service actions dispatch only after a deliberate click", () => {
  render(<ServicesView {...base} />);
  expect(base.onStart).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Thử Sandbox" }));
  expect(base.onStart).toHaveBeenCalledWith("sandbox");
  expect(screen.getByText("3/3 dịch vụ sẵn sàng")).toBeInTheDocument();
});
test("retained results survive a platform outage and report content stays escaped", () => {
  const row = {
    check_id: "42ef022a-79e9-4972-a917-3024b02740c1",
    cycle_id: "42ef022a-79e9-4972-a917-3024b02740c2",
    service: "sandbox" as const,
    state: "SUCCEEDED" as const,
    verification_evidence: false as const,
    created_at: "2026-10-21T12:00:00Z",
    updated_at: "2026-10-21T12:00:00Z",
    summary: {
      passed: true,
      exit_code: 0,
      file_round_trip: true,
      stdout: "<img src=x onerror=alert(1)>",
    },
  };
  const { container } = render(
    <ServicesView
      {...base}
      failed
      data={{
        ...data,
        capabilities: null,
        error_code: "VAI_PLATFORM_UNAVAILABLE",
        checks: [row],
      }}
    />,
  );
  expect(screen.getByText("Exit 0")).toBeInTheDocument();
  expect(screen.getByText("1/3 dịch vụ hoạt động")).toBeInTheDocument();
  expect(container.querySelector("img")).toBeNull();
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Các kết quả đã nhận vẫn được giữ lại",
  );
});
test("an unconfirmed create cannot be submitted again", () => {
  const row = {
    check_id: "42ef022a-79e9-4972-a917-3024b02740c1",
    cycle_id: "42ef022a-79e9-4972-a917-3024b02740c2",
    service: "memory" as const,
    state: "UNCONFIRMED" as const,
    verification_evidence: false as const,
    created_at: "2026-10-21T12:00:00Z",
    updated_at: "2026-10-21T12:00:00Z",
  };
  render(<ServicesView {...base} data={{ ...data, checks: [row] }} />);
  expect(screen.getByRole("button", { name: "Thử Memory" })).toBeDisabled();
  expect(screen.getByText("Chờ đối soát")).toBeInTheDocument();
  expect(
    screen.getByText(/Verify độc lập được theo dõi riêng/),
  ).toBeInTheDocument();
});
test("a working TestForge service still shows an application finding and the native checks", () => {
  const row = {
    check_id: "42ef022a-79e9-4972-a917-3024b02740c1",
    cycle_id: "42ef022a-79e9-4972-a917-3024b02740c2",
    service: "testforge" as const,
    state: "SUCCEEDED" as const,
    verification_evidence: false as const,
    created_at: "2026-10-21T12:00:00Z",
    updated_at: "2026-10-21T12:00:00Z",
    summary: {
      passed: true,
      application_passed: false,
      application_verdict: "Phát hiện lỗi",
      backend_status: "completed",
      checks_total: 5,
      checks_passed: 4,
      report: { checks: [{ label: "Nội dung nhúng", status: "FAILED" }] },
      findings: [{ label: "Nội dung nhúng", error: "Not Found" }],
    },
  };
  render(<ServicesView {...base} data={{ ...data, checks: [row] }} />);
  expect(screen.getByText("1/3 dịch vụ hoạt động")).toBeInTheDocument();
  expect(screen.getByText("Phát hiện lỗi")).toBeInTheDocument();
  expect(screen.getByText(/4\/5 kiểm tra đạt/)).toBeInTheDocument();
  expect(screen.getByText("Nội dung nhúng: Not Found")).toBeInTheDocument();
});
