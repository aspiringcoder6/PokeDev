import { useQuery } from "@tanstack/react-query";
import { getAdlcTaskLoop } from "@/controllers/API/adlc";
import useAuthStore from "@/stores/authStore";
import type { AdlcTaskRun } from "@/types/adlc";
import { readKernelEvidence, summarizeKernelEvidence } from "./kernel-evidence";

export default function KernelResults({
  deliveryId,
  runId,
  task,
  onReview,
}: {
  deliveryId: string;
  runId: string;
  task: AdlcTaskRun;
  onReview: () => void;
}) {
  const owner = useAuthStore((state) => state.userData?.id);
  const evidence = useQuery({
    queryKey: [
      "delivery-loop-evidence",
      owner ?? "unknown",
      deliveryId,
      runId,
      task.id,
      task.current_attempt_id,
      task.status,
    ],
    queryFn: async () =>
      readKernelEvidence(await getAdlcTaskLoop(runId, task.id), runId, task.id),
    retry: false,
    refetchInterval: ["RUNNING", "READY"].includes(task.status) ? 4000 : false,
  });
  const summary =
    evidence.data && !evidence.isError
      ? summarizeKernelEvidence(evidence.data, task)
      : null;
  const iteration = summary?.latest;
  return (
    <section
      className="dw-panel dw-report"
      aria-label={`Kiểm thử hệ thống: ${task.name}`}
    >
      <p className="dw-eyebrow">KIỂM THỬ DO HỆ THỐNG CHẠY</p>
      <h3>{task.name}</h3>
      {evidence.isPending ? (
        <p role="status">Đang đọc bằng chứng kiểm thử…</p>
      ) : evidence.isError ? (
        <p role="alert">
          Chưa đọc được bằng chứng kiểm thử của task này. Không suy ra kết quả
          từ trạng thái hoàn tất.
        </p>
      ) : summary?.bound ? (
        <>
          <p>
            <span
              className={`dw-pill ${summary.passed ? "dw-success" : "dw-danger"}`}
            >
              {summary.passed
                ? "Đạt trong phạm vi kiểm thử"
                : "Chưa đạt kiểm thử"}
            </span>{" "}
            <strong>{summary.tests} kiểm thử đã chạy</strong>
          </p>
          <p>
            Bản thay đổi {iteration!.iteration} ·{" "}
            {iteration!.changed_paths.join(", ") || "Không thay đổi file"}
          </p>
          <p className="dw-muted">
            Kết quả gắn với đúng candidate và bộ tiêu chí. Không tự xác nhận
            giao diện, responsive, phát hành hoặc toàn bộ ứng dụng.
          </p>
          {task.status === "WAITING_APPROVAL" && (
            <p>Candidate đang chờ bạn duyệt, chưa được bàn giao.</p>
          )}
          <details>
            <summary>Xem bằng chứng kiểm thử nâng cao</summary>
            <ul>
              {iteration!.checks.map((item) => (
                <li key={`${item.kind}:${item.check_id}`}>
                  {item.passed ? "Đạt" : "Không đạt"} · {item.label}
                  {item.executed_tests !== null &&
                    ` · ${item.executed_tests} test`}
                  {item.exit_code !== null && ` · exit ${item.exit_code}`}
                  {item.timed_out && " · quá thời gian"}
                </li>
              ))}
            </ul>
            <p className="dw-prewrap">
              Candidate: {iteration!.candidate_id}
              <br />
              {iteration!.candidate_digest}
            </p>
            <p className="dw-prewrap">
              Bộ tiêu chí: {evidence.data!.spec_digest}
            </p>
            {iteration!.duration_ms !== null && (
              <p>
                Thời gian: {(iteration!.duration_ms / 1000).toFixed(1)} giây
              </p>
            )}
          </details>
          <button className="dw-button" onClick={onReview}>
            Xem patch & bằng chứng
          </button>
        </>
      ) : (
        <p>
          Chưa đủ bằng chứng kernel gắn với candidate hiện tại. Báo cáo của
          agent, dữ liệu mô phỏng hoặc lịch sử thiếu không được coi là kiểm thử
          đã đạt.
        </p>
      )}
      <p className="dw-muted">
        Đây là kiểm thử Task Loop, tách riêng với Verify độc lập bên trên.
      </p>
      <button
        className="dw-button"
        disabled={evidence.isFetching}
        onClick={() => void evidence.refetch()}
      >
        Đọc lại bằng chứng
      </button>
    </section>
  );
}
