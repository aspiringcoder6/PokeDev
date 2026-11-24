import { useEffect, useRef, useState } from "react";
import { getAdlcTaskLoop } from "@/controllers/API/adlc";
import {
  isLiveLoop,
  readKernelEvidence,
  summarizeKernelEvidence,
} from "@/features/delivery-workspace/kernel-evidence";
import type { AdlcTaskRun } from "@/types/adlc";
import useAuthStore from "@/stores/authStore";

type EvidenceRow = {
  task: AdlcTaskRun;
  summary?: ReturnType<typeof summarizeKernelEvidence>;
};

export function useRunReviewEvidence(runId: string, tasks: AdlcTaskRun[]) {
  const owner = useAuthStore((state) => state.userData?.id);
  const live = tasks.filter(isLiveLoop);
  const scope = JSON.stringify([
    owner,
    runId,
    live.map((task) => [
      task.id,
      task.current_attempt_id,
      task.status,
      task.artifacts,
    ]),
  ]);
  const input = useRef(live);
  input.current = live;
  const [state, setState] = useState<{ scope: string; rows: EvidenceRow[] }>();
  useEffect(() => {
    let active = true;
    const snapshot = input.current;
    const load = async () => {
      const rows = await Promise.all(
        snapshot.map(async (task) => {
          try {
            const inspection = readKernelEvidence(
              await getAdlcTaskLoop(runId, task.id),
              runId,
              task.id,
            );
            return { task, summary: summarizeKernelEvidence(inspection, task) };
          } catch {
            return { task };
          }
        }),
      );
      if (active) setState({ scope, rows });
    };
    void load();
    const timer = snapshot.some((task) =>
      ["RUNNING", "READY"].includes(task.status),
    )
      ? window.setInterval(() => void load(), 4000)
      : undefined;
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [runId, scope]);
  const ready = state?.scope === scope;
  return {
    rows: ready ? state.rows : [],
    loading: live.length > 0 && !ready,
    hasLoops: live.length > 0,
  };
}

export function KernelReviewEvidence({
  evidence,
}: {
  evidence: ReturnType<typeof useRunReviewEvidence>;
}) {
  return (
    <section className="rr-quality-card" aria-label="Kiểm thử thực tế">
      <div className="rr-evidence-heading">
        <strong>Kiểm thử thực tế</strong>
        <span className="rr-kicker">Task Loop · hệ thống thực thi</span>
      </div>
      {evidence.loading ? (
        <p role="status">Đang đọc bằng chứng…</p>
      ) : evidence.rows.length ? (
        evidence.rows.map(({ task, summary }) => (
          <div key={task.id}>
            <ul className="rr-quality-list">
              <li>
                <span>{task.name}</span>
                <span
                  className={
                    summary?.passed
                      ? "rr-evidence-status"
                      : "rr-evidence-warning"
                  }
                >
                  {summary?.passed
                    ? `${summary.tests} test đã đạt`
                    : summary?.bound
                      ? "Chưa đạt kiểm thử"
                      : "Chưa đủ bằng chứng"}
                </span>
              </li>
            </ul>
            {summary?.bound && (
              <details className="rr-technical">
                <summary>Xem bằng chứng của bản thay đổi này</summary>
                <ul className="rr-quality-list">
                  {summary.latest!.checks.map((check) => (
                    <li key={check.check_id}>
                      <span>{check.label}</span>
                      <span>
                        {check.passed ? "Đạt" : "Không đạt"}
                        {check.executed_tests !== null &&
                          ` · ${check.executed_tests} test`}
                        {check.exit_code !== null &&
                          ` · exit ${check.exit_code}`}
                        {check.timed_out && " · quá thời gian"}
                      </span>
                    </li>
                  ))}
                </ul>
                <p>
                  Candidate: {summary.latest!.candidate_id}
                  <br />
                  {summary.latest!.candidate_digest}
                </p>
              </details>
            )}
          </div>
        ))
      ) : (
        <p>Chưa có bằng chứng Task Loop cho lượt chạy này.</p>
      )}
      <p>
        Chỉ xác nhận phạm vi bộ kiểm thử đã chạy; không thay thế Verify độc lập.
      </p>
    </section>
  );
}

// Presentation-only examples: no execution, receipt, pass/fail claim, or write API.
export function QualityInterfaceSamples() {
  return (
    <section aria-label="Giao diện mẫu Verify và TestForge">
      <div className="rr-evidence-heading">
        <strong>Verify & TestForge</strong>
        <span className="rr-sample-badge">
          Giao diện mẫu · không phải kết quả thật
        </span>
      </div>
      <p className="rr-approval-note mt-2 mb-4">
        Minh họa cách trình bày khi kết nối bằng chứng. Không dùng phần này để
        phê duyệt.
      </p>
      <div className="rr-quality-grid">
        <article className="rr-quality-card" aria-label="Verify mẫu">
          <div className="rr-quality-title">
            <h3>Verify độc lập</h3>
            <span className="rr-sample-badge">Chưa thực thi · mẫu</span>
          </div>
          <p>Tái hiện hành vi, rồi đối chiếu với tiêu chí đã khóa.</p>
          <div className="rr-quality-steps">
            <span>
              <i>1</i>Tiêu chí
            </span>
            <span>→</span>
            <span>
              <i>2</i>Bằng chứng
            </span>
            <span>→</span>
            <span>
              <i>3</i>Đối chiếu
            </span>
          </div>
          <ul className="rr-quality-list">
            <li>
              <span>Ví dụ: Tạo công việc</span>
              <span>Chờ bằng chứng</span>
            </li>
            <li>
              <span>Ví dụ: Đổi trạng thái</span>
              <span>Chờ bằng chứng</span>
            </li>
            <li>
              <span>Ví dụ: Xóa công việc</span>
              <span>Chờ bằng chứng</span>
            </li>
          </ul>
          <div className="rr-quality-placeholder">
            Kết luận: —<br />
            <small>Chỉ hiển thị Đạt / Không đạt khi có bằng chứng thật.</small>
          </div>
        </article>
        <article className="rr-quality-card" aria-label="TestForge mẫu">
          <div className="rr-quality-title">
            <h3>TestForge</h3>
            <span className="rr-sample-badge">Chưa thực thi · mẫu</span>
          </div>
          <p>Bộ kiểm thử cố định, báo cáo từng ca và ảnh chụp thực thi.</p>
          <div className="rr-quality-steps">
            <span>
              <i>—</i>Đạt
            </span>
            <span>
              <i>—</i>Không đạt
            </span>
            <span>
              <i>—</i>Đã chạy
            </span>
          </div>
          <ul className="rr-quality-list">
            <li>
              <span>Ví dụ: Luồng công việc</span>
              <span>Chưa chạy</span>
            </li>
            <li>
              <span>Ví dụ: Trạng thái & bộ lọc</span>
              <span>Chưa chạy</span>
            </li>
            <li>
              <span>Ví dụ: Hiển thị trên mobile</span>
              <span>Chưa chạy</span>
            </li>
          </ul>
          <div className="rr-quality-placeholder">
            Ảnh chụp & báo cáo sẽ xuất hiện ở đây
            <br />
            <small>Chưa có dữ liệu thực thi trong giao diện mẫu.</small>
          </div>
        </article>
      </div>
    </section>
  );
}
