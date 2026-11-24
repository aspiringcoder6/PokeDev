import { useQuery } from "@tanstack/react-query";
import {
  Check,
  ClipboardList,
  LoaderCircle,
  MessageCircleQuestion,
  ShieldCheck,
} from "lucide-react";
import { useRef, useState } from "react";
import {
  issueCodeMessage,
  issueError,
  projectIssues,
  type IssueProposal,
} from "@/controllers/API/project-issues";

const questions = [
  { id: "goal", question: "Kết quả cụ thể bạn muốn đạt được là gì?" },
  {
    id: "scope",
    question: "Phần nào hoặc file nào được thay đổi? Có gì cần giữ nguyên?",
  },
  {
    id: "acceptance",
    question: "Kiểm tra thế nào để biết công việc đã hoàn thành đúng?",
  },
];
const triageNames = {
  ready: "Đủ rõ để lập kế hoạch",
  needs_spec: "Cần chốt đặc tả",
  needs_human: "Cần bạn bổ sung thông tin",
};
const auditNames: Record<string, string> = {
  assessed: "Đánh giá yêu cầu và chính sách",
  clarified: "Bạn đã bổ sung thông tin",
  auto_reserved: "Đã nhận một lượt tự động",
  auto_approved: "Duyệt thực hiện theo chính sách project",
  planned: "Đã bắt đầu lập kế hoạch",
  ignored: "Đã bỏ qua đề xuất",
  restored: "Đã đưa lại đề xuất",
  policy_saved: "Đã lưu chính sách project",
  policy_upgraded: "Đã bổ sung giới hạn cho chính sách",
  auto_time_limit: "Đã dừng do hết thời gian làm việc",
  manual_approved: "Bạn đã duyệt thực hiện",
};

function Clarification({
  item,
  onChange,
}: {
  item: IssueProposal;
  onChange: () => Promise<void>;
}) {
  const needed = !!item.triage && item.triage.action !== "ready";
  const [editing, setEditing] = useState(false),
    [answers, setAnswers] = useState<Record<string, string>>(
      item.clarification?.answers || {},
    );
  const [approach, setApproach] = useState(
    item.clarification?.approach ||
      (item.triage?.action === "needs_spec" ? "spec_first" : "implement"),
  );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false);
  const inFlight = useRef(false);
  const valid = questions.every(
    (q) => (answers[q.id] || "").trim().length >= 8,
  );
  if (item.run_id)
    return item.clarification ? (
      <details className="pi-clarification-saved">
        <summary>Thông tin đã dùng để lập kế hoạch</summary>
        {questions.map((q) => (
          <div key={q.id}>
            <strong>{q.question}</strong>
            <p>{item.clarification?.answers[q.id]}</p>
          </div>
        ))}
      </details>
    ) : null;
  return (
    <section className="pi-clarification">
      {needed || editing ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (inFlight.current || !valid) return;
            inFlight.current = true;
            setBusy(true);
            setError("");
            setSaved(false);
            try {
              await projectIssues.clarify(
                item.project_id,
                item,
                answers,
                approach,
              );
              setSaved(true);
              setEditing(false);
              await onChange();
            } catch (e) {
              setError(issueError(e));
            } finally {
              inFlight.current = false;
              setBusy(false);
            }
          }}
        >
          <header>
            <MessageCircleQuestion size={17} />
            <div>
              <strong>Chốt yêu cầu trước khi giao việc</strong>
              <p>Câu trả lời được lưu cùng bản issue và đưa vào kế hoạch.</p>
            </div>
          </header>
          {questions.map((q) => (
            <label
              key={q.id}
              className="pi-field"
              htmlFor={`${item.proposal_id}-${q.id}`}
            >
              {q.question}
              <textarea
                id={`${item.proposal_id}-${q.id}`}
                rows={2}
                minLength={8}
                maxLength={4000}
                required
                value={answers[q.id] || ""}
                onChange={(e) =>
                  setAnswers({ ...answers, [q.id]: e.target.value })
                }
                disabled={busy}
              />
            </label>
          ))}
          <label className="pi-field">
            Cách bắt đầu
            <select
              value={approach}
              disabled={busy}
              onChange={(e) => setApproach(e.target.value as typeof approach)}
            >
              <option value="implement">
                Lập kế hoạch thực hiện theo yêu cầu đã chốt
              </option>
              <option value="spec_first">
                Viết đặc tả rõ ràng trước khi phân rã công việc
              </option>
            </select>
          </label>
          <div className="pi-clarification-actions">
            <small>
              Sau khi lưu, công việc tiếp tục theo chế độ duyệt của project.
            </small>
            <button
              type="submit"
              className="lw-primary"
              disabled={!valid || busy}
            >
              {busy && <LoaderCircle size={14} className="animate-spin" />}Lưu
              thông tin
            </button>
          </div>
        </form>
      ) : (
        <button
          className="pi-add-context"
          onClick={() => {
            setEditing(true);
            setSaved(false);
          }}
        >
          {item.clarification
            ? "Xem và sửa thông tin đã bổ sung"
            : "Bổ sung thông tin cho kế hoạch"}
        </button>
      )}
      {error && (
        <p role="alert" className="pi-note">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="pi-saved">
          <Check size={14} />
          Đã lưu thông tin cho bản issue này.
        </p>
      )}
    </section>
  );
}

export function IssueAuditTrail({
  item,
  identity,
}: {
  item: IssueProposal;
  identity: string;
}) {
  const [open, setOpen] = useState(false);
  const audit = useQuery({
    queryKey: ["issue-audit", identity, item.project_id, item.proposal_id],
    queryFn: () => projectIssues.audit(item.project_id, item.proposal_id),
    enabled: open,
    retry: false,
  });
  return (
    <details
      className="pi-audit"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Lịch sử quyết định</summary>
      {audit.isLoading && <p>Đang tải lịch sử…</p>}
      {audit.error && <p role="alert">{issueError(audit.error)}</p>}
      <ol>
        {audit.data?.items.map((entry) => (
          <li key={entry.id}>
            <div>
              <strong>{auditNames[entry.event] || entry.event}</strong>
              <time dateTime={entry.at}>
                {new Date(entry.at).toLocaleString("vi-VN")}
              </time>
            </div>
            <p>
              {entry.details.risk?.tier}
              {entry.details.triage &&
                ` · ${triageNames[entry.details.triage.action]}`}
              {(entry.details.policy_revision || entry.details.revision) &&
                ` · Chính sách v${entry.details.policy_revision || entry.details.revision}`}
              {entry.details.run_id &&
                ` · Lượt ${entry.details.run_id.slice(0, 8)}`}
            </p>
          </li>
        ))}
      </ol>
      {audit.data && !audit.data.items.length && (
        <p>Chưa có quyết định được ghi nhận.</p>
      )}
    </details>
  );
}

export default function IssueAssessment({
  item,
  onChange,
}: {
  item: IssueProposal;
  onChange: () => Promise<void>;
}) {
  if (!item.triage) return null;
  const needsContext = item.triage.action !== "ready";
  return (
    <div className="pi-assessment">
      <div className="pi-assessment-heading">
        {needsContext ? <ClipboardList size={17} /> : <ShieldCheck size={17} />}
        <strong>{triageNames[item.triage.action]}</strong>
        {item.risk && (
          <span className={`pi-tier r${item.risk.level}`}>
            {item.risk.preliminary ? "Dự kiến " : ""}
            {item.risk.tier}
          </span>
        )}
      </div>
      <p>{item.triage.reasons[0]}</p>
      <details className="pi-reasons">
        <summary>Vì sao có phân loại này?</summary>
        <p>
          Phân loại theo quy tắc. Mức rủi ro lấy yếu tố cao nhất và được kiểm
          tra lại trên kế hoạch thực tế.
        </p>
        <ul>
          {item.triage.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
          {item.risk?.factors.map((factor, index) => (
            <li key={`${factor.factor}-${index}`}>
              R{factor.level} · {factor.reason}
            </li>
          ))}
        </ul>
      </details>
      {item.auto_decision?.code &&
        item.auto_decision.code !== "ISSUE_REVIEW_MODE" &&
        !needsContext && (
          <p className="pi-decision">
            {issueCodeMessage(item.auto_decision.code)}
          </p>
        )}
      {!["CLOSED", "FILTERED", "IGNORED"].includes(item.state) && (
        <Clarification
          key={item.source_digest}
          item={item}
          onChange={onChange}
        />
      )}
    </div>
  );
}
