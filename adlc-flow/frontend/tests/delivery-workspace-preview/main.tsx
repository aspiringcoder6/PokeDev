import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { TooltipProvider } from "../../src/components/ui/tooltip";
import WorkspaceNavigation from "../../src/features/adlc-workspace/workspace-navigation";
import { DeliveryExperience } from "../../src/features/delivery-workspace/workspace-page";
import "../../src/i18n";
import "../../src/style/classes.css";
import "../../src/style/index.css";
import "../../src/App.css";
import "../../src/style/applies.css";
import {
  fixture,
  ids,
  taskGraphFixture,
  cycleFixture,
  cycleIds,
  cyclePlanningFixture,
} from "./fixture";

const client = new QueryClient({
  defaultOptions: { queries: { retry: false, staleTime: Infinity } },
});
client.setQueryData(["delivery-verification", ids.row, ids.run], []);
client.setQueryData(["delivery-captured-results", ids.row, ids.run], []);
function Preview() {
  const embedded =
    new URLSearchParams(window.location.search).get("embedded") === "1";
  const scenario = new URLSearchParams(window.location.search).get("scenario");
  const cycleScenario = scenario === "cycles" || scenario === "cycles-draft";
  const [selectedCycle, setSelectedCycle] = useState(
    scenario === "cycles-draft" ? cycleIds.next : cycleIds.first,
  );
  const graphScenario =
    new URLSearchParams(window.location.search).get("scenario") ===
    "task-graph";
  const [step, setStep] = useState(graphScenario ? 2 : 0);
  const [mobile, setMobile] = useState(embedded);
  const [theme, setTheme] = useState(false);
  const [notice, setNotice] = useState("");
  const row = cycleScenario
    ? cycleFixture(selectedCycle === cycleIds.next ? "draft" : "initial", true)
    : scenario === "cycle-planning"
      ? {
          ...cyclePlanningFixture(),
          permissions: { write: false, execute: false },
        }
      : graphScenario && step === 2
        ? taskGraphFixture()
        : step
          ? fixture(step)
          : null;
  if (mobile && !embedded) {
    const mobileParams = new URLSearchParams(window.location.search);
    mobileParams.set("embedded", "1");
    return (
      <div style={{ height: "100vh", background: "#f0ece6", padding: 8 }}>
        <p style={{ fontSize: 12, marginBottom: 8 }}>
          Kiểm tra giao diện · dữ liệu mẫu · viewport 390px{" "}
          <button onClick={() => setMobile(false)}>Quay lại desktop</button>
        </p>
        <iframe
          title="Bản xem điện thoại 390px"
          src={`${window.location.pathname}?${mobileParams}`}
          style={{
            display: "block",
            width: 390,
            maxWidth: "100%",
            height: "calc(100vh - 48px)",
            border: "1px solid #ccc",
            margin: "auto",
          }}
        />
      </div>
    );
  }
  return (
    <div className={theme ? "dark" : ""} style={{ height: "100vh" }}>
      <div
        style={{
          minHeight: 38,
          position: "sticky",
          top: 0,
          zIndex: 100,
          display: embedded ? "none" : "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: 14,
          padding: "8px 20px",
          background: "#f0ece6",
          color: "#655946",
          font: "11px Segoe UI",
        }}
      >
        <strong>Kiểm tra giao diện · dữ liệu mẫu, không thực thi</strong>
        {["Yêu cầu", "Workflow", "Kế hoạch", "Theo dõi", "Kết quả"].map(
          (name, i) => (
            <button key={name} onClick={() => setStep(i)}>
              {name}
            </button>
          ),
        )}
        <button onClick={() => setMobile(!mobile)}>Điện thoại</button>
        <button onClick={() => setTheme(!theme)}>Sáng / tối</button>
      </div>
      <div
        style={{
          maxWidth: mobile ? 420 : 1800,
          height: embedded ? "100%" : "calc(100% - 38px)",
          margin: "auto",
          background: theme ? "#14161c" : "#fff",
        }}
      >
        <header
          style={{
            height: 54,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "0 24px",
            borderBottom: "1px solid #e8eaee",
            color: theme ? "white" : "#222631",
            fontSize: 15,
          }}
        >
          <strong>
            ◒ &nbsp;Poke<span style={{ color: "#ed4c56" }}> Dev</span>
          </strong>
          <span style={{ fontSize: 11, color: "#7c8391" }}>
            Không gian phát triển ứng dụng
          </span>
        </header>
        <div style={{ display: "flex", height: "calc(100% - 54px)" }}>
          {!mobile && <WorkspaceNavigation />}
          <div style={{ overflow: "auto", flex: 1, minWidth: 0 }}>
            <DeliveryExperience
              key={step}
              row={row}
              items={[
                fixture(3),
                {
                  ...fixture(1),
                  id: "another",
                  title: "Cổng tiếp nhận yêu cầu",
                },
              ]}
              projects={[]}
              roles={["developer"]}
              onSelectCycle={setSelectedCycle}
              onPrepareCycle={async () =>
                setNotice("Dữ liệu mẫu, không ghi chu kỳ hoặc gọi agent.")
              }
              onUpdateCycle={async () =>
                setNotice("Dữ liệu mẫu, không sửa đặc tả trên server.")
              }
              onCreate={async () =>
                setNotice(
                  "Bản kiểm tra giao diện không gọi AI hoặc ghi dữ liệu.",
                )
              }
              onAction={async () =>
                setNotice(
                  "Đây là xác nhận trong bản kiểm tra giao diện, không thực thi.",
                )
              }
              onOpen={() => setStep(3)}
              onNew={() => setStep(0)}
              onRefresh={() =>
                setNotice("Dữ liệu mẫu không được làm mới từ server.")
              }
              onNote={async () =>
                setNotice("Không lưu dữ liệu trong bản kiểm tra giao diện.")
              }
              onAdvanced={() =>
                setNotice("Màn hình nâng cao chỉ được mở trong ứng dụng thật.")
              }
            />
          </div>
        </div>
      </div>
      {notice && (
        <button
          onClick={() => setNotice("")}
          style={{
            position: "fixed",
            bottom: 12,
            right: 12,
            padding: 16,
            background: "#202631",
            color: "white",
            borderRadius: 10,
          }}
        >
          {notice} ×
        </button>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={["/work"]}>
      <TooltipProvider>
        <Preview />
      </TooltipProvider>
    </MemoryRouter>
  </QueryClientProvider>,
);
