import { useStoreApi } from "@xyflow/react";
import { useCallback } from "react";
import { NODE_WIDTH } from "@/constants/constants";
import { useIsFlowReadOnly } from "@/contexts/permissionsContext";
import { track } from "@/customization/utils/analytics";
import useAlertStore from "@/stores/alertStore";
import useFlowStore from "@/stores/flowStore";
import type { APIClassType } from "@/types/api";
import type { AllNodeType } from "@/types/flow";
import { isAdlcBlueprint } from "@/utils/adlc-blueprint";
import { getNodeId } from "@/utils/reactflowUtils";
import { getNodeRenderType } from "@/utils/utils";

export function useAddComponent() {
  const store = useStoreApi();
  const paste = useFlowStore((state) => state.paste);
  const filterEdge = useFlowStore((state) => state.getFilterEdge);
  const filterType = useFlowStore((state) => state.filterType);
  const currentFlowId = useFlowStore((state) => state.currentFlow?.id);
  const isBlueprint = useFlowStore((state) =>
    isAdlcBlueprint(state.currentFlow),
  );
  const setErrorData = useAlertStore((state) => state.setErrorData);
  const isReadOnly = useIsFlowReadOnly(currentFlowId);

  const addComponent = useCallback(
    (
      component: APIClassType,
      type: string,
      position?: { x: number; y: number },
    ) => {
      if (isReadOnly) return;
      if (isBlueprint) {
        setErrorData({
          title: "Use a packaged workflow stage",
          list: [
            "Blueprint mode does not accept low-level Langflow components. Use Add Stage in the toolbar instead.",
          ],
        });
        return;
      }
      track("Component Added", { componentType: component.display_name });

      const {
        height,
        width,
        transform: [transformX, transformY, zoomLevel],
      } = store.getState();

      const zoomMultiplier = 1 / zoomLevel;

      let pos;

      if (position) {
        pos = position;
      } else {
        let centerX, centerY;

        centerX = -transformX * zoomMultiplier + (width * zoomMultiplier) / 2;
        centerY = -transformY * zoomMultiplier + (height * zoomMultiplier) / 2;

        const nodeOffset = NODE_WIDTH / 2;

        pos = {
          x: -nodeOffset,
          y: -nodeOffset,
          paneX: centerX,
          paneY: centerY,
        };
      }

      const newId = getNodeId(type);

      const outputType = filterType?.type;

      const outputToFilter = component.outputs?.find(
        (output) => outputType && output.types.includes(outputType),
      );

      const newNode: AllNodeType = {
        id: newId,
        type: getNodeRenderType("genericnode"),
        position: { x: 0, y: 0 },
        data: {
          node: component,
          showNode: !component.minimized,
          type: type,
          id: newId,
          ...(outputToFilter && { selected_output: outputToFilter.name }),
        },
      };

      paste({ nodes: [newNode], edges: [] }, pos);
    },
    [
      store,
      paste,
      filterEdge,
      filterType,
      isReadOnly,
      isBlueprint,
      setErrorData,
    ],
  );

  return addComponent;
}
