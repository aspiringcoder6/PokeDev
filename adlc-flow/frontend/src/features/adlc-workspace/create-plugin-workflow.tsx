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

export default function CreatePluginWorkflow() {
  const [busy, setBusy] = useState(false);
  const { folderId } = useParams();
  const defaultFolder = useFolderStore((s) => s.myCollectionId);
  const { mutateAsync } = usePostAddFlow();
  const navigate = useCustomNavigate();
  const create = async () => {
    setBusy(true);
    try {
      const response = await api.get(
        `${getBaseUrl().replace(/\/?$/, "/")}adlc/workflow-plugins/starter`,
      );
      const created = (await mutateAsync({
        ...response.data,
        folder_id: folderId ?? defaultFolder ?? "",
        is_component: false,
        mcp_enabled: false,
        endpoint_name: undefined,
        icon: "Workflow",
        gradient: undefined,
        tags: ["AgentMemory", "TestForge"],
      })) as unknown as FlowType;
      if (!created.id) throw new Error("Missing workflow acknowledgement");
      const manager = useFlowsManagerStore.getState();
      manager.setFlows([
        created,
        ...(manager.flows ?? []).filter((flow) => flow.id !== created.id),
      ]);
      manager.setCurrentFlow(created);
      navigate(`/flow/${created.id}`);
    } catch {
      useAlertStore
        .getState()
        .setErrorData({
          title: "Không thể tạo workflow plugin",
          list: [
            "Kiểm tra đăng nhập và trạng thái tích hợp plugin tại backend.",
          ],
        });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Button variant="outline" disabled={busy} onClick={() => void create()}>
      {busy ? "Đang tạo workflow…" : "Workflow AgentMemory & TestForge"}
    </Button>
  );
}
