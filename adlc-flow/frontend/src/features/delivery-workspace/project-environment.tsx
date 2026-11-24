import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  LoaderCircle,
  Plus,
  RefreshCw,
  Save,
  Trash2,
} from "lucide-react";
import { useRef, useState } from "react";
import {
  liveError,
  liveWorkflows,
  type LiveProject,
} from "@/controllers/API/live-workflows";
import {
  projectLifecycle,
  type EnvironmentProfile,
  type ProjectEnvironment as EnvironmentValue,
} from "@/controllers/API/project-lifecycle";
import "./project-lifecycle.css";

export function parseCommandLine(line: string): string[] {
  const result: string[] = [];
  let token = "",
    quote = "",
    started = false;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (quote) {
      if (char === quote) quote = "";
      else if (
        char === "\\" &&
        quote === '"' &&
        ["\\", '"'].includes(line[i + 1])
      )
        token += line[++i];
      else token += char;
    } else if (char === '"' || char === "'") {
      quote = char;
      started = true;
    } else if (/\s/.test(char)) {
      if (started) {
        result.push(token);
        token = "";
        started = false;
      }
    } else if (/[|&;<>`]/.test(char) || (char === "$" && line[i + 1] === "(")) {
      throw new Error(
        "Mỗi dòng là một lệnh. Tách các lệnh nối bằng && hoặc pipe thành các dòng riêng.",
      );
    } else {
      token += char;
      started = true;
    }
  }
  if (quote) throw new Error("Lệnh còn thiếu dấu nháy đóng.");
  if (started) result.push(token);
  if (result.some((part) => !part))
    throw new Error("Đối số của lệnh không được để trống.");
  return result;
}

function formatCommand(argv: string[]) {
  return argv
    .map((arg) => (/^[\w./:@=+,-]+$/.test(arg) ? arg : JSON.stringify(arg)))
    .join(" ");
}

function EnvironmentForm({
  value,
  project,
  identity,
}: {
  value: EnvironmentValue;
  project: LiveProject;
  identity: string;
}) {
  const client = useQueryClient();
  const [draft, setDraft] = useState(value.profile);
  const [revision, setRevision] = useState(value.revision);
  const [saved, setSaved] = useState(value);
  const [dirty, setDirty] = useState(false),
    [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [timeout, setTimeoutSeconds] = useState(
    value.profile.tests[0]?.timeout || 180,
  );
  const [commands, setCommands] = useState(
    Object.fromEntries(
      ["setup", "tests", "build"].map((stage) => [
        stage,
        value.profile[stage as "setup" | "tests" | "build"]
          .map((command) => formatCommand(command.argv))
          .join("\n"),
      ]),
    ),
  );
  const [previewKind, setPreviewKind] = useState(
    value.profile.preview?.argv
      ? "command"
      : value.profile.preview?.path
        ? "static"
        : "none",
  );
  const [previewValue, setPreviewValue] = useState(
    value.profile.preview?.argv
      ? formatCommand(value.profile.preview.argv)
      : value.profile.preview?.path || ".",
  );
  const [checkId, setCheckId] = useState(value.last_check?.check_id || "");
  const checkIntent = useRef<{ digest: string; id: string } | null>(null);
  const inFlight = useRef(false);
  const repositories = useQuery({
    queryKey: ["environment-repositories", identity],
    queryFn: liveWorkflows.repositories,
    retry: false,
  });
  const check = useQuery({
    queryKey: ["environment-check", identity, project.project_id, checkId],
    queryFn: () => projectLifecycle.readCheck(project.project_id, checkId),
    enabled: !!checkId,
    retry: false,
    refetchInterval: (q) =>
      ["PREPARING", "RUNNING", "UNCONFIRMED"].includes(
        q.state.data?.state || "PREPARING",
      )
        ? 5000
        : false,
  });
  const change = (patch: Partial<EnvironmentProfile>) => {
    setDraft({ ...draft, ...patch });
    setDirty(true);
  };
  const operation = async (name: string, work: () => Promise<void>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(name);
    setError("");
    try {
      await work();
    } catch (e) {
      setError(
        e instanceof Error && !("response" in e) ? e.message : liveError(e),
      );
    } finally {
      inFlight.current = false;
      setBusy("");
    }
  };
  const receipt = check.data || value.last_check;
  const currentCheck = receipt?.environment_digest === saved.digest;
  return (
    <div className="pl-environment">
      <header className="pl-heading">
        <div>
          <span className="lw-eyebrow">MÔI TRƯỜNG CỦA PROJECT</span>
          <h2>Chuẩn bị để chạy trên code thật</h2>
          <p>
            {project.repository} ·{" "}
            {revision
              ? `Cấu hình phiên bản ${revision}`
              : "Chưa có cấu hình riêng"}
          </p>
        </div>
        <span
          className={`pl-badge ${dirty ? "pending" : revision ? "ok" : "pending"}`}
        >
          {dirty
            ? "Có thay đổi chưa lưu"
            : revision
              ? "Đã lưu"
              : "Cần thiết lập"}
        </span>
      </header>
      <p className="pl-note">
        Cấu hình đã lưu được cố định khi tạo lượt mới. Lệnh trong môi trường sẽ
        là lệnh kiểm chứng của lượt đó; các lượt đang chạy giữ nguyên cấu hình
        cũ. Các lệnh chạy trong Sandbox của Harness.
      </p>
      {(error || check.error) && (
        <p className="lw-alert" role="alert">
          {error || liveError(check.error)}
        </p>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void operation("Đang lưu môi trường", async () => {
            const profile: EnvironmentProfile = {
              ...draft,
              ...Object.fromEntries(
                ["setup", "tests", "build"].map((stage) => [
                  stage,
                  commands[stage]
                    .split("\n")
                    .map((line) => line.trim())
                    .filter(Boolean)
                    .map((line, i) => ({
                      label: `${{ setup: "Cài đặt", tests: "Kiểm thử", build: "Build" }[stage]} ${i + 1}`,
                      argv: parseCommandLine(line),
                      timeout,
                    })),
                ]),
              ),
              preview:
                previewKind === "none"
                  ? null
                  : previewKind === "static"
                    ? { path: previewValue.trim() }
                    : { argv: parseCommandLine(previewValue) },
              base: draft.base
                ? {
                    repository_id: draft.base.repository_id,
                    ...(draft.base.commit
                      ? { commit: draft.base.commit.trim() }
                      : {}),
                  }
                : null,
            };
            const result = await projectLifecycle.saveEnvironment(
              project.project_id,
              revision,
              profile,
            );
            setSaved(result);
            setDraft(result.profile);
            setRevision(result.revision);
            setDirty(false);
            await client.invalidateQueries({
              queryKey: ["project-environment", identity, project.project_id],
            });
          });
        }}
      >
        <div className="pl-grid">
          <label>
            Tên môi trường
            <input
              value={draft.name}
              maxLength={120}
              onChange={(e) => change({ name: e.target.value })}
            />
          </label>
          <label>
            Thư mục chạy lệnh
            <input
              value={draft.working_directory}
              placeholder=". hoặc apps/web"
              onChange={(e) => change({ working_directory: e.target.value })}
            />
            <small>Tính từ thư mục gốc workspace đã ghép.</small>
          </label>
        </div>
        <fieldset>
          <legend>Nguồn và cách ghép module</legend>
          <p className="pl-note">
            Nếu repo chính chỉ chứa module, chọn thêm một repo khung. Commit để
            trống sẽ cố định bản mới nhất khi lưu. File sửa và nhánh xuất lên
            Gitea vẫn thuộc repo chính.
          </p>
          <div className="pl-grid">
            <label>
              Repo khung
              <select
                value={draft.base?.repository_id || ""}
                onChange={(e) =>
                  change({
                    base: e.target.value
                      ? { repository_id: Number(e.target.value) }
                      : null,
                    overlays: e.target.value ? draft.overlays : [],
                  })
                }
              >
                <option value="">Dùng riêng repo chính</option>
                {repositories.data?.items.map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.full_name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Commit repo khung
              <input
                disabled={!draft.base}
                value={draft.base?.commit || ""}
                placeholder="Để trống để lấy bản mới nhất"
                onChange={(e) =>
                  draft.base &&
                  change({ base: { ...draft.base, commit: e.target.value } })
                }
              />
            </label>
          </div>
          {repositories.error && (
            <p role="alert">{liveError(repositories.error)}</p>
          )}
          {draft.base && (
            <>
              <div className="pl-mappings">
                {draft.overlays.map((mapping, index) => (
                  <div key={index}>
                    <label>
                      Thư mục trong repo chính
                      <small>Dùng dấu . nếu ghép toàn bộ repo chính.</small>
                      <input
                        aria-label={`Nguồn module ${index + 1}`}
                        value={mapping.source}
                        placeholder="FE/military-youth-develop"
                        onChange={(e) =>
                          change({
                            overlays: draft.overlays.map((m, i) =>
                              i === index
                                ? { ...m, source: e.target.value }
                                : m,
                            ),
                          })
                        }
                      />
                    </label>
                    <span>→</span>
                    <label>
                      Thư mục trong repo khung
                      <input
                        aria-label={`Đích module ${index + 1}`}
                        value={mapping.target}
                        placeholder="src/app/modules/military-youth"
                        onChange={(e) =>
                          change({
                            overlays: draft.overlays.map((m, i) =>
                              i === index
                                ? { ...m, target: e.target.value }
                                : m,
                            ),
                          })
                        }
                      />
                    </label>
                    <button
                      type="button"
                      aria-label={`Xóa module ${index + 1}`}
                      onClick={() =>
                        change({
                          overlays: draft.overlays.filter(
                            (_, i) => i !== index,
                          ),
                        })
                      }
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                disabled={draft.overlays.length >= 8}
                onClick={() =>
                  change({
                    overlays: [...draft.overlays, { source: "", target: "" }],
                  })
                }
              >
                <Plus size={14} />
                Thêm module
              </button>
            </>
          )}
        </fieldset>
        <fieldset>
          <legend>Cài đặt, kiểm thử và build</legend>
          <p className="pl-note">
            Mỗi dòng một lệnh, tối đa 8 lệnh cho cả ba nhóm. Ví dụ:{" "}
            <code>npm ci</code>, <code>npm run build</code>. Không nhập mật khẩu
            hoặc token vào lệnh.
          </p>
          <div className="pl-command-grid">
            {(
              [
                ["setup", "Cài dependency", "npm ci"],
                [
                  "tests",
                  "Kiểm thử bắt buộc",
                  "python -m unittest discover -s tests -v",
                ],
                ["build", "Build", "npm run build"],
              ] as const
            ).map(([stage, label, placeholder]) => (
              <label key={stage}>
                {label}
                <textarea
                  aria-label={label}
                  rows={5}
                  value={commands[stage]}
                  placeholder={placeholder}
                  onChange={(e) => {
                    setCommands({ ...commands, [stage]: e.target.value });
                    setDirty(true);
                  }}
                />
              </label>
            ))}
          </div>
          <label className="pl-timeout">
            Thời gian chờ mỗi lệnh (giây)
            <input
              type="number"
              min={5}
              max={600}
              value={timeout}
              onChange={(e) => {
                setTimeoutSeconds(Number(e.target.value));
                setDirty(true);
              }}
            />
          </label>
        </fieldset>
        <fieldset>
          <legend>Xem ứng dụng sau kiểm thử</legend>
          <div className="pl-grid">
            <label>
              Kiểu preview
              <select
                value={previewKind}
                onChange={(e) => {
                  setPreviewKind(e.target.value);
                  setPreviewValue(e.target.value === "static" ? "." : "");
                  setDirty(true);
                }}
              >
                <option value="none">Không có preview</option>
                <option value="static">Thư mục web tĩnh</option>
                <option value="command">Lệnh khởi động ứng dụng</option>
              </select>
            </label>
            {previewKind !== "none" && (
              <label>
                {previewKind === "static"
                  ? "Thư mục chứa trang web"
                  : "Lệnh khởi động"}
                <input
                  value={previewValue}
                  placeholder={
                    previewKind === "static"
                      ? "dist"
                      : "npm start -- --host 0.0.0.0 --port 8088"
                  }
                  onChange={(e) => {
                    setPreviewValue(e.target.value);
                    setDirty(true);
                  }}
                />
                <small>
                  Ứng dụng cần nghe ở cổng 8088. Đường dẫn tính từ thư mục chạy
                  lệnh.
                </small>
              </label>
            )}
          </div>
        </fieldset>
        <div className="pl-actions">
          <button
            className="lw-primary"
            type="submit"
            disabled={!!busy || (!dirty && revision > 0)}
          >
            <Save size={15} />
            Lưu môi trường
          </button>
          <button
            type="button"
            disabled={!!busy || dirty || !saved.digest}
            onClick={() =>
              void operation("Đang chuẩn bị kiểm tra", async () => {
                if (!saved.digest) return;
                if (
                  check.data &&
                  ["SUCCEEDED", "FAILED"].includes(check.data.state)
                )
                  checkIntent.current = null;
                if (checkIntent.current?.digest !== saved.digest)
                  checkIntent.current = {
                    digest: saved.digest,
                    id: crypto.randomUUID(),
                  };
                const result = await projectLifecycle.checkEnvironment(
                  project.project_id,
                  checkIntent.current.id,
                  saved.digest,
                );
                setCheckId(result.check_id);
              })
            }
          >
            <RefreshCw size={15} />
            Kiểm tra môi trường
          </button>
          {busy && (
            <span>
              <LoaderCircle size={14} className="animate-spin" />
              {busy}
            </span>
          )}
        </div>
      </form>
      {receipt && (
        <section className="pl-check" aria-label="Kết quả kiểm tra môi trường">
          <header>
            <h3>
              {receipt.state === "SUCCEEDED" ? (
                <CheckCircle2 size={18} />
              ) : (
                <RefreshCw size={18} />
              )}
              Kết quả kiểm tra baseline
            </h3>
            <span
              className={`pl-badge ${receipt.state === "SUCCEEDED" ? "ok" : "pending"}`}
            >
              {receipt.state === "SUCCEEDED"
                ? "Đạt"
                : receipt.state === "FAILED"
                  ? "Cần xử lý"
                  : "Đang kiểm tra / đối soát"}
            </span>
          </header>
          {!currentCheck && (
            <p className="pl-note">
              Kết quả này thuộc cấu hình cũ. Kiểm tra lại cấu hình vừa lưu.
            </p>
          )}
          <p className="pl-note">
            Kiểm tra chạy cài đặt, test và build trên source hiện tại. Baseline
            có lỗi vẫn có thể được dùng để lập kế hoạch sửa; kết quả này chưa
            chứng minh thay đổi của Agent.
          </p>
          {receipt.base_commit && (
            <code>Source @{receipt.base_commit.slice(0, 12)}</code>
          )}
          {receipt.error_code && (
            <p>{liveError({ code: receipt.error_code })}</p>
          )}
          {receipt.receipt?.checks.map((item) => (
            <details key={item.id}>
              <summary>
                {item.passed ? "✓" : "×"} {item.label}
              </summary>
              <pre>
                {[item.stdout, item.stderr].filter(Boolean).join("\n") ||
                  "Không có log bổ sung."}
              </pre>
            </details>
          ))}
          <button
            type="button"
            disabled={check.isFetching}
            onClick={() => void check.refetch()}
          >
            <RefreshCw size={14} />
            Cập nhật kết quả
          </button>
        </section>
      )}
    </div>
  );
}

export default function ProjectEnvironment({
  project,
  identity,
}: {
  project?: LiveProject;
  identity: string;
}) {
  const environment = useQuery({
    queryKey: ["project-environment", identity, project?.project_id],
    queryFn: () => projectLifecycle.environment(project!.project_id),
    enabled: !!project,
    retry: false,
  });
  if (!project)
    return (
      <div className="pl-empty">
        <h2>Chọn project để thiết lập môi trường</h2>
        <p>Mỗi project giữ riêng nguồn, cách ghép module và lệnh kiểm chứng.</p>
      </div>
    );
  if (environment.error)
    return (
      <p className="lw-alert" role="alert">
        {liveError(environment.error)}
      </p>
    );
  if (!environment.data) return <p className="pl-note">Đang đọc môi trường…</p>;
  return (
    <EnvironmentForm
      key={`${identity}:${project.project_id}`}
      value={environment.data}
      project={project}
      identity={identity}
    />
  );
}
