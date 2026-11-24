import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  BellRing,
  LoaderCircle,
  MessageCircleQuestion,
  ShieldCheck,
} from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useSearchParams } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { AuthContext } from "@/contexts/authContext";
import {
  type HumanInput,
  type HumanAttention,
  liveError,
  liveWorkflows,
} from "@/controllers/API/live-workflows";
import "./human-input.css";
import { projectWorkloop } from "@/controllers/API/project-workloop";
import { documentUrl } from "@/controllers/API/document-intake";
import { documentNeedsReview, useDocumentInbox } from "./document-intake-query";

export const humanRunUrl = (item: {
  project_id: string;
  run_id: string;
  kind?: string;
  proposal_id?: string;
  job_id?: string;
  document_id?: string;
}) =>
  item.kind === "document"
    ? documentUrl(item.document_id || item.run_id, item.project_id || undefined)
    : item.kind === "workloop"
      ? "/work?" +
        new URLSearchParams({
          project: item.project_id,
          workloop_job: item.job_id || item.run_id,
          tab: "attention",
        })
      : item.kind === "advanced"
        ? "/runs/" + encodeURIComponent(item.run_id)
        : item.kind === "issue"
          ? "/work?" +
            new URLSearchParams({
              project: item.project_id,
              view: "issues",
              issue: item.proposal_id || "",
            })
          : "/work?" +
            new URLSearchParams({ project: item.project_id, run: item.run_id });

export function useHumanAttention() {
  const { userData } = useContext(AuthContext);
  return useQuery({
    queryKey: ["human-attention", userData?.id || "pending"],
    queryFn: liveWorkflows.attention,
    enabled: !!userData,
    retry: false,
    staleTime: 1500,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  });
}

type AnswerDraft = Record<string, { selected: string[]; custom: string }>;

export function HumanInputCard({
  request,
  onAnswer,
  draft,
  onDraftChange,
}: {
  request: HumanInput;
  draft?: AnswerDraft;
  onDraftChange?: (value: AnswerDraft) => void;
  onAnswer: (
    response: Record<string, unknown>,
    commandId: string,
  ) => Promise<unknown>;
}) {
  const [localAnswers, setAnswers] = useState<AnswerDraft>({});
  const answers = draft || localAnswers;
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const sending = useRef(false);
  const intent = useRef<{ key: string; id: string } | undefined>(undefined);
  const disabled = busy || !request.can_respond;
  const complete = request.questions?.every((q) => {
    const value = answers[q.id];
    return !!value && (!!value.selected.length || !!value.custom.trim());
  });
  const submit = async (response: Record<string, unknown>) => {
    if (sending.current || !request.can_respond) return;
    const key = JSON.stringify(response);
    if (!intent.current || intent.current.key !== key)
      intent.current = { key, id: crypto.randomUUID() };
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      await onAnswer(response, intent.current.id);
    } catch (e) {
      setError(liveError(e));
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };
  return (
    <section
      className="hi-card"
      id={`human-input-${request.request_id}`}
      tabIndex={-1}
      aria-label={request.title}
    >
      <header>
        {request.kind === "question" ? (
          <MessageCircleQuestion size={20} />
        ) : (
          <ShieldCheck size={20} />
        )}
        <div>
          <h3>{request.title}</h3>
          <p>
            {request.node_title} · {request.run_title}
          </p>
        </div>
        <span>Đang chờ bạn</span>
      </header>
      {request.origin === "workflow_gate" && (
        <p className="hi-gate-context">
          Cổng duyệt · lần {1 + (request.gate_round || 0)}. Xem{" "}
          <strong>Thay đổi source</strong> và <strong>Test & Verify</strong> của
          lượt chạy trước khi quyết định.{" "}
          <small>Kết quả: {request.source_digest?.slice(0, 12)}</small>
        </p>
      )}
      {request.kind === "question" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (complete)
              void submit({
                answers: request.questions!.map((q) => ({
                  id: q.id,
                  selected: answers[q.id]?.selected || [],
                  ...(answers[q.id]?.custom.trim()
                    ? { custom: answers[q.id].custom.trim() }
                    : {}),
                })),
              });
          }}
        >
          {request.questions?.map((q, index) => {
            const value = answers[q.id] || { selected: [], custom: "" };
            const change = (next: Partial<typeof value>) => {
              const updated = { ...answers, [q.id]: { ...value, ...next } };
              setAnswers(updated);
              onDraftChange?.(updated);
            };
            return (
              <fieldset key={q.id} disabled={disabled}>
                <legend>{q.question}</legend>
                {q.multi_select && (
                  <p className="hi-help">Có thể chọn nhiều phương án.</p>
                )}
                <div className="hi-options">
                  {q.options.map((option) => (
                    <label key={option.label}>
                      <input
                        type={q.multi_select ? "checkbox" : "radio"}
                        name={request.request_id + ":" + q.id}
                        checked={value.selected.includes(option.label)}
                        onChange={() =>
                          change({
                            selected: q.multi_select
                              ? value.selected.includes(option.label)
                                ? value.selected.filter(
                                    (x) => x !== option.label,
                                  )
                                : [...value.selected, option.label]
                              : [option.label],
                          })
                        }
                      />
                      <span>
                        <strong>{option.label}</strong>
                        {option.description && (
                          <small>{option.description}</small>
                        )}
                      </span>
                    </label>
                  ))}
                </div>
                <label
                  className="hi-custom"
                  htmlFor={request.request_id + ":custom:" + index}
                >
                  {q.options.length
                    ? "Câu trả lời khác hoặc thông tin bổ sung"
                    : "Câu trả lời của bạn"}
                </label>
                <textarea
                  id={request.request_id + ":custom:" + index}
                  maxLength={8000}
                  rows={3}
                  value={value.custom}
                  onChange={(e) => change({ custom: e.target.value })}
                />
              </fieldset>
            );
          })}
          <button
            className="hi-primary"
            type="submit"
            disabled={disabled || !complete}
          >
            {busy && <LoaderCircle className="animate-spin" size={15} />} Gửi
            câu trả lời
          </button>
        </form>
      ) : (
        <div>
          <p className="hi-permission-tool">
            Công cụ: <strong>{request.tool_name}</strong>
          </p>
          <p className="hi-prompt">{request.prompt}</p>
          {request.details && Object.keys(request.details).length > 0 && (
            <details>
              <summary>Xem hành động được yêu cầu</summary>
              <pre>{JSON.stringify(request.details, null, 2)}</pre>
            </details>
          )}
          <div className="hi-actions">
            <button
              className="hi-primary"
              disabled={disabled}
              onClick={() => void submit({ decision: "allowed-once" })}
            >
              Cho phép lần này
            </button>
            <button
              disabled={disabled}
              onClick={() => void submit({ decision: "rejected" })}
            >
              Từ chối
            </button>
          </div>
        </div>
      )}
      {error && (
        <p role="alert" className="hi-error">
          {error}
        </p>
      )}
      {!request.can_respond && (
        <p role="status" className="hi-help">
          {request.status === "UNCERTAIN"
            ? "Đang xác nhận phản hồi. Giữ nội dung của bạn và chờ kết nối lại."
            : "Đang kết nối lại để gửi phản hồi. Câu trả lời của bạn vẫn được giữ."}
        </p>
      )}
    </section>
  );
}

export function RunHumanInputs({ runId }: { runId: string }) {
  const [params] = useSearchParams();
  const focus = params.get("focus");
  const focused = useRef("");
  const attention = useHumanAttention(),
    client = useQueryClient();
  const [sent, setSent] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, AnswerDraft>>({});
  const requests =
    attention.data?.requests.filter((q) => q.run_id === runId) || [];
  useEffect(() => {
    if (!focus || focused.current === `${runId}:${focus}`) return;
    const target = document.getElementById(
      focus === "recovery" ? "run-recovery" : `human-input-${focus}`,
    );
    if (target) {
      target.scrollIntoView?.({ block: "center", behavior: "smooth" });
      target.focus({ preventScroll: true });
      focused.current = `${runId}:${focus}`;
    }
  }, [focus, runId, attention.data]);
  return (
    <div className="hi-run" aria-live="polite">
      {focus &&
        focus !== "recovery" &&
        !attention.isPending &&
        !attention.isError &&
        !requests.some((q) => q.request_id === focus) && (
          <p className="hi-sent" role="status">
            Yêu cầu này không còn trong danh sách chờ. Kiểm tra trạng thái lượt
            chạy và lịch sử phản hồi.
          </p>
        )}
      {requests.length > 0 && (
        <p className="hi-heading">Công việc đang chờ phản hồi của bạn</p>
      )}
      {requests.map((request) => (
        <HumanInputCard
          key={request.request_id}
          request={request}
          draft={drafts[request.request_id]}
          onDraftChange={(draft) =>
            setDrafts((old) => ({ ...old, [request.request_id]: draft }))
          }
          onAnswer={async (response, command) => {
            await liveWorkflows.answer(request, command, response);
            setDrafts((old) => {
              const next = { ...old };
              delete next[request.request_id];
              return next;
            });
            setSent(true);
            await Promise.all([
              client.invalidateQueries({ queryKey: ["human-attention"] }),
              client.invalidateQueries({ queryKey: ["live-run"] }),
              client.invalidateQueries({ queryKey: ["live-runs"] }),
              client.invalidateQueries({ queryKey: ["workspace-dashboard"] }),
            ]);
          }}
        />
      ))}
      {sent && requests.length === 0 && (
        <p role="status" className="hi-sent">
          Đã gửi phản hồi cho Agent. Công việc có thể tiếp tục.
        </p>
      )}
    </div>
  );
}

export default function HumanInputNotifications() {
  const { userData } = useContext(AuthContext),
    attention = useHumanAttention();
  const documents = useDocumentInbox();
  const external = useQuery({
    queryKey: ["workloop-attention", userData?.id],
    queryFn: projectWorkloop.attention,
    enabled: !!userData,
    retry: false,
    refetchInterval: 10000,
    refetchIntervalInBackground: true,
  });
  const [open, setOpen] = useState(false),
    [permission, setPermission] = useState(
      typeof Notification === "undefined"
        ? "unsupported"
        : Notification.permission,
    );
  const notified = useRef(new Set<string>());
  const hidden = [401, 403].includes(
    (external.error as { response?: { status?: number } })?.response?.status ||
      0,
  );
  const externalReviews = hidden
    ? []
    : (external.data?.items || []).flatMap((job) =>
        job.requests.map((request) => ({
          request_id: `workloop:${job.job_id}:${request.request_id}`,
          project_id: job.project_id,
          run_id: job.job_id,
          kind: "workloop" as const,
          run_title: job.title,
          title: `Workloop · ${request.title}`,
        })),
      );
  const documentDenied = [401, 403, 404].includes(
    (documents.error as { response?: { status?: number } })?.response?.status ||
      0,
  );
  const documentReviews: HumanAttention["reviews"] = documentDenied
    ? []
    : (documents.data?.items || [])
        .filter(
          (doc) =>
            documentNeedsReview(doc) ||
            !!(doc.progress?.enabled && doc.progress.error_code),
        )
        .map((doc) => ({
          request_id: `document:${doc.document_id}:${doc.progress?.enabled && doc.progress.error_code ? `progress:${doc.progress.error_code}` : doc.state === "CHANGED" ? doc.page_digest : "pending"}`,
          project_id: doc.project_id || "",
          run_id: doc.document_id,
          document_id: doc.document_id,
          kind: "document",
          run_title: doc.title,
          title:
            doc.progress?.enabled && doc.progress.error_code
              ? "Đồng bộ tiến độ Slack cần kiểm tra"
              : doc.state === "NEEDS_PROJECT"
                ? "Yêu cầu Slack cần chọn project"
                : doc.state === "CHANGED"
                  ? "Tài liệu thay đổi cần xem lại"
                  : "Tài liệu chờ duyệt cho project",
        }));
  const requests = attention.data?.requests || [],
    reviews = [
      ...(attention.data?.reviews || []),
      ...externalReviews,
      ...documentReviews,
    ];
  const count = requests.length + reviews.length;
  const disconnected =
    !!attention.data?.active_runs &&
    (!attention.data.connected || attention.isError);
  useEffect(() => {
    const newIssues: HumanAttention["reviews"] = [];
    for (const item of [...requests, ...reviews]) {
      const key = userData?.id + ":" + item.request_id;
      if (notified.current.has(key)) continue;
      notified.current.add(key);
      if (item.kind === "issue") {
        newIssues.push(item);
        continue;
      }
      if (
        typeof Notification !== "undefined" &&
        Notification.permission === "granted"
      ) {
        const notice = new Notification(item.title, {
          body: item.run_title,
          tag: key,
        });
        notice.onclick = () => {
          window.focus();
          window.location.assign(humanRunUrl(item));
          notice.close();
        };
      }
    }
    if (
      newIssues.length &&
      typeof Notification !== "undefined" &&
      Notification.permission === "granted"
    ) {
      const first = newIssues[0];
      const notice = new Notification(
        `${newIssues.length} đề xuất từ issue Gitea`,
        { body: first.run_title, tag: userData?.id + ":gitea-issues" },
      );
      notice.onclick = () => {
        window.focus();
        window.location.assign(humanRunUrl(first));
        notice.close();
      };
    }
  }, [
    attention.data,
    external.data,
    documents.data,
    documentDenied,
    userData?.id,
  ]);
  if (!userData) return null;
  return (
    <>
      <button
        className={`hi-bell ${count || disconnected || attention.isError ? "hi-bell-pending" : ""}`}
        aria-label={
          count ? `Cần bạn phản hồi: ${count}` : "Thông báo công việc"
        }
        onClick={() => setOpen(true)}
      >
        {count ? <BellRing size={18} /> : <Bell size={18} />}
        <span role="status">
          {count
            ? `${count} việc đang chờ bạn`
            : attention.isError
              ? "Chưa cập nhật được thông báo"
              : disconnected
                ? "Đang kết nối kênh phản hồi"
                : "Thông báo"}
        </span>
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="hi-inbox">
          <DialogTitle>Thông báo công việc</DialogTitle>
          <DialogDescription>
            Câu hỏi, tài liệu Slack, kế hoạch và issue đang chờ bạn xem.
          </DialogDescription>
          {(disconnected || attention.isError) && (
            <p role="alert" className="hi-error">
              Chưa nhận được câu hỏi từ Harness. Kiểm tra VPN; PokeDev đang
              tự kết nối lại.
            </p>
          )}
          {(external.isError || external.data?.partial) && (
            <p role="alert" className="hi-error">
              Chưa cập nhật đủ thông báo Workloop. Mở project để xem dữ liệu đã
              lưu và kiểm tra kết nối.
            </p>
          )}
          {(documents.isError || documents.data?.stale) && (
            <p role="alert" className="hi-error">
              Chưa cập nhật được tài liệu từ Workloop. Những yêu cầu đã nhận vẫn
              được giữ trong hộp yêu cầu.
            </p>
          )}
          <div className="hi-inbox-items">
            {[...requests, ...reviews].map((item) => (
              <Link
                key={item.request_id}
                to={humanRunUrl(item)}
                onClick={() => setOpen(false)}
              >
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.run_title}</p>
                </div>
                <span>
                  {item.kind === "plan"
                    ? "Xem kế hoạch"
                    : item.kind === "advanced"
                      ? "Xem công việc"
                      : item.kind === "issue"
                        ? "Xem đề xuất"
                        : item.kind === "document"
                          ? "Xem tài liệu"
                          : item.kind === "recovery"
                            ? "Tiếp tục lượt chạy"
                            : "Trả lời"}{" "}
                  →
                </span>
              </Link>
            ))}
            {!count && (
              <p className="hi-help">
                Hiện không có việc nào chờ bạn phản hồi.
              </p>
            )}
          </div>
          {permission !== "unsupported" && permission !== "granted" && (
            <button
              className="hi-enable"
              onClick={async () => {
                try {
                  setPermission(await Notification.requestPermission());
                } catch {
                  setPermission("denied");
                }
              }}
              disabled={permission === "denied"}
            >
              Bật thông báo máy tính
            </button>
          )}
          <p className="hi-help">
            Thông báo được cập nhật khi PokeDev đang mở.
            {permission === "denied" &&
              " Bạn có thể cho phép thông báo trong cài đặt của trình duyệt."}
          </p>
        </DialogContent>
      </Dialog>
    </>
  );
}
