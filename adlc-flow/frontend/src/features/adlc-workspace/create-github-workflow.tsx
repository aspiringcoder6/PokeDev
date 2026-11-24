import { useState } from "react";
import { useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { api } from "@/controllers/API/api";
import { usePostAddFlow } from "@/controllers/API/queries/flows/use-post-add-flow";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { getBaseUrl } from "@/customization/utils/urls";
import useAlertStore from "@/stores/alertStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import { useFolderStore } from "@/stores/foldersStore";
import type { FlowType } from "@/types/flow";

export default function CreateGithubWorkflow() {
  const [busy, setBusy] = useState(false);
  const { folderId } = useParams();
  const defaultFolder = useFolderStore((s) => s.myCollectionId);
  const { mutateAsync } = usePostAddFlow();
  const navigate = useCustomNavigate();
  const create = async () => {
    setBusy(true);
    try {
      const response = await api.get(
        `${getBaseUrl().replace(/\/?$/, "/")}adlc/harness-workflows/starter`,
      );
      const saved = await mutateAsync({
        ...response.data,
        folder_id: folderId ?? defaultFolder ?? "",
        is_component: false,
        mcp_enabled: false,
        endpoint_name: undefined,
        icon: "GitBranch",
        gradient: undefined,
        tags: ["Harness", "GitHub"],
      });
      const created = saved as unknown as FlowType;
      if (!created.id)
        throw new Error("Workflow creation acknowledgement is missing.");
      const manager = useFlowsManagerStore.getState();
      manager.setFlows([
        created,
        ...(manager.flows ?? []).filter((f) => f.id !== created.id),
      ]);
      manager.setCurrentFlow(created);
      navigate(`/flow/${created.id}`);
    } catch {
      useAlertStore.getState().setErrorData({
        title: "Không thể tạo workflow GitHub",
        list: [
          "Kiểm tra đăng nhập và kết nối Harness; nếu tên đã tồn tại, mở workflow đã lưu trong Workflows. Không có model hoặc push nào được khởi động.",
        ],
      });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button variant="outline" disabled={busy} onClick={() => void create()}>
      {busy ? "Đang tạo workflow…" : "Tạo workflow GitHub"}
    </Button>
  );
}
