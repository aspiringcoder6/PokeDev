import { translateUi, useUiLocale, formatUiDateTime } from "@/i18n/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, History, LockKeyhole, ShieldCheck, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  createTeamProject,
  revokeTeamMember,
  roleIds,
  saveTeamPolicy,
  setTeamMember,
  type TeamAccessView,
  type TeamPolicy,
  type TeamRoleId,
  teamAudit,
  teamEffective,
  teamError,
  teamProject,
  teamProjects,
} from "@/controllers/API/team-access";
import useAuthStore from "@/stores/authStore";

const names: Record<TeamRoleId, string> = {
  admin: "Admin",
  developer: "Developer",
  business_analyst: "Business Analyst",
  tester: "Tester",
};
const descriptions: Record<TeamRoleId, string> = {
  admin: "Thành viên & chính sách",
  developer: "Triển khai & bàn giao",
  business_analyst: "Yêu cầu & nghiệp vụ",
  tester: "Kiểm thử & nghiệm thu",
};
const reserved = new Set([
  "policy:manage",
  "membership:manage",
  "audit:read",
  "integration:manage",
]);
const protectedAdmin = new Set([
  "project:read",
  "policy:read",
  "policy:manage",
  "membership:manage",
  "audit:read",
]);
type Draft = { revision: number; before: TeamPolicy; policy: TeamPolicy };
const copy = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

export function policyDiff(before: TeamPolicy, after: TeamPolicy) {
  return roleIds.flatMap((role) =>
    ["allow", "deny"].flatMap((effect) => {
      const kind = effect as "allow" | "deny";
      const keys = new Set([
        ...before.roles[role][kind],
        ...after.roles[role][kind],
      ]);
      return [...keys]
        .filter(
          (key) =>
            before.roles[role][kind].includes(key) !==
            after.roles[role][kind].includes(key),
        )
        .map((key) => ({
          role,
          effect: kind,
          key,
          enabled: after.roles[role][kind].includes(key),
        }));
    }),
  );
}

export default function TeamAccessPage() {
  const identity = useAuthStore((store) => store.userData?.id);
  const client = useQueryClient();
  const key = ["team-access", identity];
  const [projectId, setProjectId] = useState("");
  const [newName, setNewName] = useState("");
  const [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const projects = useQuery({
    queryKey: [...key, "projects"],
    queryFn: teamProjects,
    enabled: !!identity,
    refetchOnWindowFocus: true,
  });
  const selected = projectId || projects.data?.projects[0]?.project_id || "";
  const project = useQuery({
    queryKey: [...key, selected],
    queryFn: () => teamProject(selected),
    enabled: !!identity && !!selected,
    refetchInterval: 30000,
  });
  const create = useMutation({
    mutationFn: () => createTeamProject(newName),
    onSuccess: async (data) => {
      setProjectId(data.project_id);
      setNewName("");
      setMessage(
        "Đã tạo project rỗng với Admin khởi tạo là tài khoản của bạn.",
      );
      client.setQueryData([...key, data.project_id], data);
      await client.invalidateQueries({ queryKey: [...key, "projects"] });
    },
  });
  return (
    <main className="h-full w-full overflow-auto p-5 lg:p-8">
      <div className="mx-auto max-w-6xl space-y-6">
        <header>
          <p className="mb-2 text-xs font-medium text-primary">
            PokeDev · Quản trị project
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">
            Thành viên & phân quyền
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Bốn vai trò, quyền theo project và quyết định có thể truy vết.
          </p>
        </header>
        <div className="flex items-start gap-3 rounded-xl border bg-card p-4 text-sm">
          <ShieldCheck className="shrink-0 text-primary" size={19} />
          <div>
            <p className="font-medium">
              {project.data?.mode === "COLLABORATION" ? "H7B · Cộng tác theo project, chưa mở thực thi agent" : "H7A · Quản trị thật, chưa mở thực thi chung"}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              Chỉ khởi tạo project mới, rỗng. Workflow, contract và lịch sử
              riêng hiện tại không tự động được chia sẻ. Quyền H7B chỉ có hiệu
              lực sau khi mở cộng tác; các quyền thực thi H7C vẫn đang khóa.
            </p>
          </div>
        </div>
        {!identity && (
          <p role="alert">Hãy đăng nhập để xác minh quyền của bạn.</p>
        )}
        {projects.isLoading && (
          <p role="status">Đang xác minh danh tính và quyền project…</p>
        )}
        {projects.isError && (
          <div
            role="alert"
            className="rounded-lg border p-4 text-sm text-destructive"
          >
            {teamError(projects.error)}{" "}
            <Button variant="outline" onClick={() => projects.refetch()}>
              Thử lại
            </Button>
          </div>
        )}
        {message && (
          <p role="status" className="text-sm text-primary">
            {message}
          </p>
        )}
        {projects.data && (
          <div className="flex flex-wrap items-end justify-between gap-4">
            <label className="grid gap-2 text-xs font-medium">
              Project đang quản trị
              <select
                className="min-w-52 rounded-lg border bg-background p-2 text-sm"
                value={selected}
                onChange={(event) => setProjectId(event.target.value)}
                disabled={projects.isFetching || dirty || create.isPending}
              >
                <option value="" disabled>
                  Chọn project
                </option>
                {projects.data.projects.map((item) => (
                  <option key={item.project_id} value={item.project_id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
            {projects.data.can_create && (
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!dirty) create.mutate();
                }}
              >
                <label className="grid gap-2 text-xs font-medium">
                  Khởi tạo project riêng cho team
                  <input
                    aria-label="Tên project mới"
                    minLength={2}
                    maxLength={80}
                    required
                    className="rounded-lg border bg-background p-2 text-sm"
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    placeholder="Tên project mới"
                  />
                </label>
                <Button
                  type="submit"
                  disabled={
                    dirty ||
                    create.isPending ||
                    newName.trim().length < 2 ||
                    projects.isError
                  }
                >
                  Tạo project rỗng
                </Button>
              </form>
            )}
          </div>
        )}
        {create.isError && (
          <p role="alert" className="text-sm text-destructive">
            {teamError(create.error)}
          </p>
        )}
        {projects.data?.projects.length === 0 && (
          <div className="rounded-xl border border-dashed p-10 text-center">
            <Users className="mx-auto text-muted-foreground" />
            <h2 className="mt-3 font-medium">
              Chưa có project được phân quyền
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {projects.data.can_create
                ? "Tạo một project rỗng ở trên để thiết lập bốn role và thành viên."
                : "Nhờ Admin project thêm username ADLC của bạn. Người tạo tài nguyên không tự động được cấp quyền quản trị."}
            </p>
          </div>
        )}
        {project.isLoading && selected && (
          <p role="status">Đang tải chính sách… Mọi thao tác vẫn đang khóa.</p>
        )}
        {project.isError && (
          <p
            role="alert"
            className="rounded-xl border p-4 text-sm text-destructive"
          >
            {teamError(project.error)}
          </p>
        )}
        {project.data && !project.isError && (
          <ProjectAccess
            key={`${identity}:${selected}`}
            data={project.data}
            pending={project.isFetching}
            onDirty={setDirty}
            refresh={async () => {
              await client.invalidateQueries({ queryKey: key });
            }}
            onLeave={() => {
              setProjectId("");
              client.removeQueries({
                queryKey: [...key, selected],
                exact: true,
              });
            }}
          />
        )}
      </div>
    </main>
  );
}

function ProjectAccess({
  data,
  pending,
  refresh,
  onLeave,
  onDirty,
}: {
  data: TeamAccessView;
  pending: boolean;
  refresh: () => Promise<void>;
  onLeave: () => void;
  onDirty: (dirty: boolean) => void;
}) {
  useUiLocale();
  const [role, setRole] = useState<TeamRoleId>(
    data.can_manage ? "developer" : data.effective.roles[0],
  );
  const [tab, setTab] = useState("policy");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [preview, setPreview] = useState(false);
  const [username, setUsername] = useState("");
  const [memberRole, setMemberRole] = useState<TeamRoleId>("developer");
  const [memberReview, setMemberReview] = useState<{
    username: string;
    role: TeamRoleId;
    revision: number;
  } | null>(null);
  const [revoke, setRevoke] = useState<{
    subject: string;
    username: string;
    revision: number;
  } | null>(null);
  const [subject, setSubject] = useState(data.effective.user_id);
  const [success, setSuccess] = useState("");
  const policy = draft?.policy || data.policy;
  const differences =
    data.policy && policy
      ? policyDiff(draft?.before || data.policy, policy)
      : [];
  useEffect(() => {
    onDirty(differences.length > 0);
    return () => onDirty(false);
  }, [differences.length, onDirty]);
  const stale = !!draft && draft.revision !== data.revision;
  const canEdit = data.can_manage && !pending && !stale;
  const effective = useQuery({
    queryKey: [
      "team-access-effective",
      data.project_id,
      data.effective.user_id,
      subject,
      data.revision,
    ],
    queryFn: () => teamEffective(data.project_id, subject),
    enabled: tab === "effective" && !!subject,
    refetchOnWindowFocus: true,
  });
  const audit = useQuery({
    queryKey: [
      "team-access-audit",
      data.project_id,
      data.effective.user_id,
      data.revision,
    ],
    queryFn: () => teamAudit(data.project_id),
    enabled: tab === "audit" && data.can_manage,
  });
  const save = useMutation({
    mutationFn: () =>
      saveTeamPolicy(data.project_id, draft!.revision, draft!.policy),
    onSuccess: async () => {
      setDraft(null);
      setPreview(false);
      setSuccess("Đã lưu chính sách và audit cùng giao dịch.");
      await refresh();
    },
    onError: () => refresh(),
  });
  const member = useMutation({
    mutationFn: () =>
      setTeamMember(
        data.project_id,
        memberReview!.revision,
        memberReview!.username,
        [memberReview!.role],
      ),
    onSuccess: async () => {
      setUsername("");
      setMemberReview(null);
      setSuccess("Đã cập nhật thành viên theo đúng scope project.");
      await refresh();
    },
    onError: () => refresh(),
  });
  const removal = useMutation({
    mutationFn: () =>
      revokeTeamMember(data.project_id, revoke!.revision, revoke!.subject),
    onSuccess: async () => {
      const own = revoke?.subject === data.effective.user_id;
      setRevoke(null);
      await refresh();
      if (own) onLeave();
      else
        setSuccess(
          "Đã thu hồi membership. Các worker sẽ kiểm tra lại ở request tiếp theo.",
        );
    },
    onError: () => refresh(),
  });
  const busy = save.isPending || member.isPending || removal.isPending;
  function toggle(action: string, effect: "allow" | "deny", checked: boolean) {
    if (!canEdit || !data.policy) return;
    const next = copy(policy!);
    next.roles[role][effect] = next.roles[role][effect].filter(
      (key) => key !== action,
    );
    if (checked) {
      next.roles[role][effect].push(action);
      const opposite = effect === "allow" ? "deny" : "allow";
      next.roles[role][opposite] = next.roles[role][opposite].filter(
        (key) => key !== action,
      );
    }
    setDraft({
      revision: draft?.revision || data.revision,
      before: draft?.before || copy(data.policy),
      policy: next,
    });
    setSuccess("");
  }
  return (
    <section aria-label={`Phân quyền ${data.name}`} className="space-y-5">
      <div
        className="flex flex-wrap gap-5 border-b"
        role="tablist"
        aria-label="Quản trị project"
      >
        {[
          ["policy", "Vai trò & quyền"],
          ["members", "Thành viên"],
          ["effective", "Quyền hiệu lực"],
          ...(data.can_manage ? [["audit", "Nhật ký"]] : []),
        ].map(([id, label]) => (
          <button
            type="button"
            key={id}
            role="tab"
            id={`team-tab-${id}`}
            aria-controls="team-panel"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`border-b-2 px-1 pb-3 text-sm ${tab === id ? "border-primary text-primary" : "border-transparent text-muted-foreground"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id="team-panel"
        aria-labelledby={`team-tab-${tab}`}
        className="space-y-5"
      >
        {success && (
          <p role="status" className="text-sm text-primary">
            {success}
          </p>
        )}
        {(save.error || member.error || removal.error) && (
          <p role="alert" className="text-sm text-destructive">
            {teamError(save.error || member.error || removal.error)}
          </p>
        )}
        {stale && (
          <p
            role="alert"
            className="rounded-lg border p-3 text-sm text-destructive"
          >
            Chính sách đã có phiên bản mới. Bản nháp được giữ lại để đối chiếu;
            hãy hoàn tác và tải lại trước khi sửa tiếp.
          </p>
        )}
        {tab === "policy" && (
          <>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {data.roles
                .filter(
                  (item) =>
                    data.can_manage || data.effective.roles.includes(item.id),
                )
                .map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    aria-pressed={role === item.id}
                    onClick={() => setRole(item.id)}
                    className={`rounded-xl border p-4 text-left ${role === item.id ? "border-primary bg-primary/10" : "bg-card"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">{item.name}</span>
                      {role === item.id && (
                        <Check size={15} className="text-primary" />
                      )}
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {descriptions[item.id]}
                    </p>
                    <p className="mt-3 text-xs text-muted-foreground">
                      {data.can_manage
                        ? `${data.members.filter((person) => person.roles.includes(item.id)).length} thành viên`
                        : "Vai trò của bạn"}
                    </p>
                  </button>
                ))}
            </div>
            <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_240px]">
              <div className="overflow-hidden rounded-xl border bg-card">
                <div className="border-b p-4">
                  <h2 className="font-medium">Quyền của {names[role]}</h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Allow được hợp nhất giữa các role. Deny có ưu tiên cao hơn;
                    các chốt an toàn vẫn bắt buộc.
                  </p>
                </div>
                <PermissionRows
                  data={data}
                  role={role}
                  policy={policy}
                  canEdit={canEdit && !busy}
                  toggle={toggle}
                  future={false}
                />
                <details className="border-t">
                  <summary className="cursor-pointer p-4 text-sm">
                    {data.mode === "COLLABORATION" ? "Quyền chuẩn bị cho H7C — chưa mở thực thi" : "Quyền chuẩn bị cho H7B / H7C — chưa mở thực thi"}
                  </summary>
                  <PermissionRows
                    data={data}
                    role={role}
                    policy={policy}
                    canEdit={canEdit && !busy}
                    toggle={toggle}
                    future
                  />
                </details>
              </div>
              <aside className="space-y-4 rounded-xl border bg-card p-4">
                <h2 className="text-sm font-medium">Phạm vi & bảo vệ</h2>
                <p className="text-sm">{data.name}</p>
                <p className="text-xs text-muted-foreground">
                  Chính sách v{data.revision} · Chỉ cấu hình
                </p>
                {[
                  "Không tự nâng quyền toàn hệ thống",
                  "Bảo vệ Admin có hiệu lực cuối cùng",
                  "Không sửa contract hoặc bằng chứng đã khóa",
                  "Agent không nhận quyền quản trị hoặc token push",
                ].map((text) => (
                  <p
                    key={text}
                    className="flex items-start gap-2 text-xs leading-5 text-muted-foreground"
                  >
                    <LockKeyhole size={13} className="mt-1 shrink-0" />
                    {text}
                  </p>
                ))}
              </aside>
            </div>
            {data.can_manage && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4">
                <div>
                  <p className="text-sm font-medium">
                    {differences.length
                      ? `${differences.length} thay đổi chưa lưu`
                      : `Chính sách v${data.revision} · Không có thay đổi`}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Lưu quyền yêu cầu đúng phiên bản, xác thực cá nhân và audit
                    thành công.
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    disabled={!draft || busy}
                    onClick={() => {
                      setDraft(null);
                      setPreview(false);
                    }}
                  >
                    Hoàn tác
                  </Button>
                  <Button
                    disabled={!differences.length || !canEdit || busy}
                    onClick={() => setPreview(true)}
                  >
                    Xem thay đổi
                  </Button>
                </div>
              </div>
            )}
          </>
        )}
        {tab === "members" && (
          <>
            {data.can_manage ? (
              <>
                <form
                  className="flex flex-wrap items-end gap-3 rounded-xl border bg-card p-4"
                  onSubmit={(event) => {
                    event.preventDefault();
                    setMemberReview({
                      username: username.trim(),
                      role: memberRole,
                      revision: data.revision,
                    });
                  }}
                >
                  <label className="grid gap-2 text-xs">
                    Username ADLC có sẵn
                    <input
                      aria-label="Username thành viên"
                      required
                      maxLength={128}
                      className="rounded-lg border bg-background p-2 text-sm"
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                    />
                  </label>
                  <label className="grid gap-2 text-xs">
                    Vai trò
                    <select
                      aria-label="Vai trò thành viên"
                      value={memberRole}
                      onChange={(event) =>
                        setMemberRole(event.target.value as TeamRoleId)
                      }
                      className="rounded-lg border bg-background p-2 text-sm"
                    >
                      {data.roles.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    type="submit"
                    disabled={busy || pending || !username.trim() || !!draft}
                  >
                    Thêm / thay role
                  </Button>
                  <p className="w-full text-xs text-muted-foreground">
                    Không tạo tài khoản, không gửi email. Thao tác thay bộ role
                    hiện tại bằng role đã chọn, sau kiểm tra Admin cuối cùng.
                  </p>
                </form>
                <div className="overflow-x-auto rounded-xl border">
                  <table className="w-full text-left text-sm">
                    <thead className="bg-muted">
                      <tr>
                        <th className="p-3">Thành viên</th>
                        <th className="p-3">Vai trò</th>
                        <th className="p-3">Trạng thái</th>
                        <th className="p-3">Thao tác</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.members.map((person) => (
                        <tr key={person.user_id} className="border-t">
                          <td className="p-3">
                            {person.username}
                            {person.user_id === data.effective.user_id && (
                              <span className="ml-2 text-xs text-muted-foreground">
                                (Bạn)
                              </span>
                            )}
                          </td>
                          <td className="p-3">
                            {person.roles.map((item) => names[item]).join(", ")}
                          </td>
                          <td className="p-3 text-xs">
                            {person.is_active
                              ? "Đang hoạt động"
                              : "Đã vô hiệu hóa"}
                          </td>
                          <td className="p-3">
                            <Button
                              variant="outline"
                              disabled={busy || pending || !!draft}
                              onClick={() =>
                                setRevoke({
                                  subject: person.user_id,
                                  username: person.username,
                                  revision: data.revision,
                                })
                              }
                            >
                              Thu hồi
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="rounded-xl border p-5 text-sm text-muted-foreground">
                Chỉ người có quyền quản trị thành viên được xem danh sách và
                thay đổi membership. Bạn có thể xem quyền của mình tại tab Quyền
                hiệu lực.
              </p>
            )}
          </>
        )}
        {tab === "effective" && (
          <>
            <label className="grid max-w-sm gap-2 text-xs">
              Kiểm tra quyền của
              <select
                aria-label="Thành viên kiểm tra quyền"
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                className="rounded-lg border bg-background p-2 text-sm"
              >
                {(data.can_manage
                  ? data.members
                  : [{ user_id: data.effective.user_id, username: "Tôi" }]
                ).map((person) => (
                  <option key={person.user_id} value={person.user_id}>
                    {person.username}
                  </option>
                ))}
              </select>
            </label>
            {effective.isLoading && (
              <p role="status">Đang kiểm tra chính sách hiện tại…</p>
            )}
            {effective.isError && (
              <p role="alert" className="text-sm text-destructive">
                {teamError(effective.error)}
              </p>
            )}
            {effective.data && !effective.isError && (
              <div className="overflow-x-auto rounded-xl border">
                <table className="w-full text-left text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="p-3">Hành động</th>
                      <th className="p-3">Quyền hiệu lực</th>
                      <th className="p-3">Lý do</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.catalog.map((action) => (
                      <tr key={action.key} className="border-t">
                        <td className="p-3">{action.label}</td>
                        <td className="p-3">
                          {effective.data.permissions[action.key]?.allowed
                            ? "Được phép"
                            : "Không được phép"}
                        </td>
                        <td className="p-3 text-xs text-muted-foreground">
                          {effective.data.permissions[action.key]?.reason ===
                          "TEAM_SHARED_EXECUTION_NOT_ENABLED"
                            ? `Chưa mở · ${action.phase}`
                            : effective.data.permissions[action.key]?.reason ||
                              "Không xác định — khóa an toàn"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
        {tab === "audit" && data.can_manage && (
          <div className="rounded-xl border bg-card p-4">
            <h2 className="mb-4 flex items-center gap-2 font-medium">
              <History size={17} />
              Nhật ký phân quyền
            </h2>
            {audit.isLoading && <p role="status">Đang tải…</p>}
            {audit.isError && <p role="alert">{teamError(audit.error)}</p>}
            {audit.data?.map((entry) => (
              <article key={entry.id} className="border-t py-4 text-sm">
                <p>{entry.action}</p>
                <p className="mt-1 break-all text-xs text-muted-foreground">
                  {translateUi("Actor:")}{" "}
                  {entry.actor_username || entry.actor_id} {translateUi("· v")}
                  {String(entry.details?.policy_revision || "—")} ·{" "}
                  {formatUiDateTime(new Date(entry.occurred_at))}
                </p>
              </article>
            ))}
          </div>
        )}
      </div>
      {preview && (
        <Dialog
          open={preview}
          onOpenChange={(open) => {
            if (!busy) setPreview(open);
          }}
        >
          <DialogContent className="max-h-[85vh] overflow-y-auto">
            <DialogTitle className="font-semibold">
              Xem trước thay đổi quyền
            </DialogTitle>
            <DialogDescription className="mt-2 text-sm text-muted-foreground">
              {
                new Set(
                  data.members
                    .filter((person) =>
                      differences.some((change) =>
                        person.roles.includes(change.role),
                      ),
                    )
                    .map((person) => person.user_id),
                ).size
              }{" "}
              thành viên bị ảnh hưởng · v{draft?.revision} {translateUi("→ v")}
              {(draft?.revision || 0) + 1}
            </DialogDescription>
            <ul className="my-4 space-y-2 text-sm">
              {differences.map((change) => (
                <li key={`${change.role}:${change.effect}:${change.key}`}>
                  {names[change.role]} · {change.key} · {change.effect}:{" "}
                  {change.enabled ? "Bật" : "Tắt"}
                </li>
              ))}
            </ul>
            {save.error && (
              <p role="alert" className="text-sm text-destructive">
                {teamError(save.error)}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setPreview(false)}
                disabled={busy}
              >
                Quay lại
              </Button>
              <Button
                disabled={!canEdit || busy || !differences.length}
                onClick={() => save.mutate()}
              >
                Lưu chính sách
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
      {memberReview && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open && !busy) setMemberReview(null);
          }}
        >
          <DialogContent>
            <DialogTitle>Xác nhận bộ role trong project</DialogTitle>
            <DialogDescription>
              {memberReview.username} · {data.name} · chính sách v
              {memberReview.revision}. Thay bộ role hiện tại bằng{" "}
              {names[memberReview.role]}; không cấp quyền toàn hệ thống.
            </DialogDescription>
            {member.error && (
              <p role="alert" className="text-sm text-destructive">
                {teamError(member.error)}
              </p>
            )}
            {memberReview.revision !== data.revision && (
              <p role="alert">
                Chính sách đã thay đổi. Đóng hồ sơ và kiểm tra lại trước khi xác
                nhận.
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setMemberReview(null)}
              >
                Hủy
              </Button>
              <Button
                disabled={
                  busy ||
                  pending ||
                  !data.can_manage ||
                  memberReview.revision !== data.revision
                }
                onClick={() => member.mutate()}
              >
                Xác nhận gán role
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
      {revoke && (
        <Dialog
          open
          onOpenChange={(open) => {
            if (!open && !busy) setRevoke(null);
          }}
        >
          <DialogContent>
            <DialogTitle className="font-medium">
              Thu hồi toàn bộ role trong project?
            </DialogTitle>
            <DialogDescription className="my-3 text-sm text-muted-foreground">
              {revoke.username} · {data.name} {translateUi("· v")}
              {revoke.revision}. Không xóa tài khoản hoặc lịch sử. Không thể
              loại bỏ Admin có hiệu lực cuối cùng.
            </DialogDescription>
            {removal.error && (
              <p role="alert" className="text-sm text-destructive">
                {teamError(removal.error)}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => setRevoke(null)}
                disabled={busy}
              >
                Hủy
              </Button>
              <Button
                disabled={
                  busy ||
                  pending ||
                  !data.can_manage ||
                  revoke.revision !== data.revision
                }
                onClick={() => removal.mutate()}
              >
                Xác nhận thu hồi
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </section>
  );
}

function PermissionRows({
  data,
  role,
  policy,
  canEdit,
  toggle,
  future,
}: {
  data: TeamAccessView;
  role: TeamRoleId;
  policy: TeamPolicy | null;
  canEdit: boolean;
  toggle: (key: string, effect: "allow" | "deny", checked: boolean) => void;
  future: boolean;
}) {
  useUiLocale();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="bg-muted text-muted-foreground">
          <tr>
            <th className="p-3">Hành động</th>
            <th className="p-3 text-center">{translateUi("Allow")}</th>
            <th className="p-3 text-center">{translateUi("Deny")}</th>
            <th className="p-3">Hiệu lực</th>
          </tr>
        </thead>
        <tbody>
          {data.catalog
            .filter((action) => !(action.phase === "H7A" || (data.mode === "COLLABORATION" && action.phase === "H7B")) === future)
            .map((action) => {
              const fixed = role === "admin" && protectedAdmin.has(action.key);
              const reservedAllow =
                role !== "admin" && reserved.has(action.key);
              return (
                <tr className="border-t" key={action.key}>
                  <td className="p-3">
                    <p>{action.label}</p>
                    <p className="mt-1 text-[10px] text-muted-foreground">
                      {action.area}
                    </p>
                  </td>
                  {(["allow", "deny"] as const).map((effect) => (
                    <td key={effect} className="p-3 text-center">
                      <input
                        type="checkbox"
                        className="accent-primary"
                        aria-label={`${names[role]}: ${action.label} — ${effect}`}
                        checked={
                          policy
                            ? policy.roles[role][effect].includes(action.key)
                            : effect === "allow" &&
                              !!data.effective.permissions[action.key]?.granted
                        }
                        disabled={
                          !canEdit ||
                          fixed ||
                          (effect === "allow" && reservedAllow)
                        }
                        onChange={(event) =>
                          toggle(action.key, effect, event.target.checked)
                        }
                      />
                    </td>
                  ))}
                  <td className="p-3 text-muted-foreground">
                    {action.phase === "H7A" || (data.mode === "COLLABORATION" && action.phase === "H7B")
                      ? "Đang áp dụng"
                      : `${action.phase} · Chưa mở`}
                  </td>
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
