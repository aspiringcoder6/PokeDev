import { Download, FileJson2, Upload, Check, RotateCcw } from "lucide-react";
import { useRef } from "react";
import type { WorkflowGraph } from "@/controllers/API/live-workflows";

export default function WorkflowJsonEditor({
  graph,
  draft,
  error,
  onDraft,
  onError,
  onApply,
  onDiscard,
}: {
  graph: WorkflowGraph;
  draft: string | null;
  error: string;
  onDraft: (text: string) => void;
  onError: (text: string) => void;
  onApply: () => void;
  onDiscard: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const download = () => {
    const blob = new Blob([JSON.stringify(graph, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob),
      link = document.createElement("a");
    link.href = url;
    link.download = "vaiplatform-workflow.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="wc-json-panel">
      <div className="wc-json-intro">
        <span className="lw-eyebrow">DÀNH CHO NGƯỜI DÙNG NÂNG CAO</span>
        <h3>
          <FileJson2 size={20} />
          Chỉnh workflow bằng JSON
        </h3>
        <p>
          Sửa toàn bộ đồ thị, nhập cấu hình hoặc xuất để dùng lại. Áp dụng JSON
          để xem trên canvas, sau đó lưu workflow. Các lượt chạy hiện có giữ
          nguyên phiên bản của chúng.
        </p>
        <div className="wc-actions">
          <button onClick={() => input.current?.click()}>
            <Upload size={14} />
            Nhập từ file
          </button>
          <button onClick={download}>
            <Download size={14} />
            Xuất cấu hình hiện tại
          </button>
        </div>
        <input
          ref={input}
          type="file"
          accept=".json,application/json"
          aria-label="Nhập file workflow JSON"
          hidden
          onChange={async (event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (!file) return;
            if (file.size > 400_000) {
              onError("File JSON tối đa 400 KB.");
              return;
            }
            try {
              onDraft(await file.text());
            } catch {
              onError("Không đọc được file. Hãy chọn lại.");
            }
          }}
        />
        <div className="wc-info">
          <strong>Cấu hình được hỗ trợ</strong>
          <p>
            Developer, Tester, Reviewer; điều kiện; kiểm chứng; cổng duyệt người
            dùng hoặc Agent; gộp nhánh và vòng sửa giới hạn 0–3.
          </p>
        </div>
        <p className="wc-hint">
          Tên workflow và project được quản lý riêng ở thanh đầu trang và mục
          Kiểm chứng & preview. Máy chủ kiểm tra quyền sửa file, phụ thuộc và
          khả năng thực thi khi lưu.
        </p>
      </div>
      <div className="wc-json-code">
        <label htmlFor="workflow-json">
          Cấu trúc workflow{" "}
          <span>
            {draft !== null ? "Có thay đổi chưa áp dụng" : "Đồng bộ với canvas"}
          </span>
        </label>
        <textarea
          id="workflow-json"
          spellCheck={false}
          value={draft ?? JSON.stringify(graph, null, 2)}
          onChange={(e) => onDraft(e.target.value)}
        />
        {error && (
          <p className="wc-validation" role="alert">
            {error}
          </p>
        )}
        <div className="wc-actions">
          <button
            className="lw-primary"
            disabled={draft === null}
            onClick={onApply}
          >
            <Check size={14} />
            Áp dụng JSON vào canvas
          </button>
          <button disabled={draft === null && !error} onClick={onDiscard}>
            <RotateCcw size={14} />
            Bỏ chỉnh sửa JSON
          </button>
        </div>
      </div>
    </div>
  );
}
