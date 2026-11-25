---
name: vai-sandbox
description: Quy trình chuẩn làm việc với vAi Sandbox (remote code execution + VFS git). Dùng khi cần clone/sửa/build/test code trên sandbox server, hoặc làm việc với repo như một thành viên (branch/commit/push). KHÔNG dùng cho thao tác file local trên máy DSH.
---

# vAi Sandbox — Quy trình chuẩn

## Hai khái niệm PHÂN BIỆT (quan trọng nhất)

| Khái niệm | Là gì | Sống bao lâu |
|---|---|---|
| `workspace_id` | VFS workspace trên server — **bản code bền vững** (git repo thật + SQLite) | Vĩnh viễn cho tới khi xóa |
| `session_id` | Container + runner đang chạy | Chết theo `ttl` hoặc bất cứ lúc nào → ALWAYS set ttl (VD 3600) |

**Quy tắc vàng:** sửa code bền = QUALIFY bằng `workspace_id` (tools `sandbox_vfs_*`, `sandbox_git_*` — không cần session sống). Chạy lện/build = `session_id` (cần runner sống).

## Luồng A — Làm việc với repo như một thành viên (KHÔNG cần sandbox sống)

1. `sandbox_git_clone {workspace_id: <tên-mới>, url, branch}` — clone về VFS (dùng `token` nếu repo riêng; không truyền thì tự lấy `VAI_GIT_TOKEN`).
2. `sandbox_git_branch {workspace_id, branch: "agent-<tên>", checkout: true, role: "agent"}` — role `agent` CHỈ được branch bắt đầu `agent-` (policy server, 403 nếu sai).
3. Đọc/sửa qua VFS: `sandbox_vfs_read` → `sandbox_vfs_write` (ghi đè nguyên file; **file nhị phân** — ảnh chụp màn hình từ steel, PDF, zip — truyền `content_base64` + `is_binary: true`, bỏ tiền tố `data:image/...`) — hoặc `sandbox_vfs_files` để liệt kê.
4. `sandbox_git_commit {workspace_id, message}` — author mặc định `vai-agent <agent@vaiplatform.local>`.
5. `sandbox_git_push {workspace_id}` — push branch `agent-*` về remote.

Gặp lỗi 404 "No active runner" CHỈ áp dụng cho tools session (`sandbox_shell`...) — Luồng A không dính.

## Luồng B — Build/test code trong container

1. `sandbox_create {project_path: <workspace_id>, image, cpu, memory, ttl: 3600}` — `project_path` PHẢI trùng `workspace_id` của VFS để code được auto-sync vào container trước mỗi shell.
2. `sandbox_status` — chờ `runnerConnected: true` (~5s).
3. `sandbox_shell {session_id, command}` — build/test chạy тут. Chỉnh file trong container là TẠM THỜI (VFS là master; lần shell sau sync đè lại theo VFS đã commit) — muốn bền: sửa qua Luồng A.
4. Xong: `sandbox_delete` (hoặc để ttl tự dọn).

**Session chết giữa chừng** (404 No active runner): tạo session mới cùng `project_path` và chạy lại — code nằm yên trong VFS, không mất gì.

## Token & cấu hình (đã có sẵn trong Secrets vault)

- `VAI_SANDBOX_BROKER_URL` — URL broker (đặt rồi, hot-reload).
- `VAI_SANDBOX_TOKEN` — token broker (nếu bật auth).
- `VAI_GIT_TOKEN` — PAT git (GitHub/GitLab/Gitea) cho clone/push repo riêng.

## Lưu ảnh / nhị phân VÀO workspace DSH (bắt buộc đọc khi xử lý ảnh)

VFS workspace (trên sandbox server) **KHÔNG PHẢI** filesystem DSH của bạn — file ghi vào VFS không hiện ra
thư mục dự án. Muốn xuất file PNG/PDF/bytes NƠI `read`/`present` nhìn thấy (workspace DSH), dùng đúng 1 tool:

```
sandbox_save_file {
  path: "shots/chinhphu.png"      # workspace-relative
  url: "<link ảnh/PDF>"            # HOẶC content_base64 (raw base64) HOẶC content (text)
}
→ {ok, path: "/app/workspace/shots/chinhphu.png", bytes}
→ present(path) / read(path) chạy được ngay; file hiện trong Web UI file tree.
```

Quy trình chụp màn hình web bằng Steel:
1. `mcp__steel__navigate {url}` rồi `mcp__steel__steel_screenshot` (inline:false) → nhận link ảnh.
2. `sandbox_save_file {path: "shots/<tên>.png", url: <link>}`.
3. `present(/app/workspace/shots/<tên>.png)`.

## Ví dụ nhanh

Clone repo nội bộ Gitea và mở branch sửa:
```
sandbox_git_clone {workspace_id: "feature-x", url: "http://10.0.10.195:3000/admin/agent-harness-server.git", branch: "master"}
sandbox_git_branch {workspace_id: "feature-x", branch: "agent-fix-readme", checkout: true}
sandbox_vfs_write {workspace_id: "feature-x", path: "NOTES.md", content: "# Ghi chu\nBuoi hop 2026-09-19\n"}
sandbox_git_commit {workspace_id: "feature-x", message: "docs: them ghi chu buoi hop"}
sandbox_git_push {workspace_id: "feature-x"}
```
