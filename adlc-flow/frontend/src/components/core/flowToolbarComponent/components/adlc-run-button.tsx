import { translateUi, useUiLocale } from "@/i18n/ui";
import axios from "axios";
import { useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePermissions } from "@/contexts/permissionsContext";
import { createAdlcRun } from "@/controllers/API/adlc";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useSaveFlow from "@/hooks/flows/use-save-flow";
import useAlertStore from "@/stores/alertStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import { isAdlcBlueprint } from "@/utils/adlc-blueprint";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail?.message === "string") return detail.message;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error
    ? error.message
    : translateUi("Unable to start ADLC run.");
}

const AdlcRunButton = () => {
  useUiLocale();
  const [isRunning, setIsRunning] = useState(false);
  const currentFlow = useFlowStore((state) => state.currentFlow);
  const currentFlowId = useFlowsManagerStore((state) => state.currentFlowId);
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const saveFlow = useSaveFlow();
  const navigate = useCustomNavigate();
  const { can } = usePermissions();
  const canRun = can(currentFlowId, "execute");

  if (isAdlcBlueprint(currentFlow)) return null;

  const startRun = async () => {
    if (!currentFlowId || !canRun || isRunning) return;
    setIsRunning(true);
    try {
      await saveFlow();
      const run = await createAdlcRun(currentFlowId);
      navigate(`/runs/${run.id}`);
    } catch (error) {
      setErrorData({
        title: translateUi("Unable to start ADLC run"),
        list: [errorMessage(error)],
      });
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <>
      <Badge
        variant="secondaryStatic"
        size="sq"
        className="ml-1"
        title={translateUi(
          "Runs the saved component graph through the legacy ADLC mock path.",
        )}
        data-testid="adlc-execution-mode-badge"
      >
        {translateUi("Legacy flow")}
      </Badge>
      <Button
        type="button"
        variant="ghost"
        size="md"
        className="h-8 gap-1.5 px-2 font-normal"
        disabled={!currentFlowId || !canRun}
        loading={isRunning}
        onClick={startRun}
        ignoreTitleCase
        data-testid="run-as-adlc-button"
      >
        <ForwardedIconComponent name="Play" className="h-4 w-4" />
        {translateUi("Run as ADLC")}
      </Button>
    </>
  );
};

export default AdlcRunButton;
