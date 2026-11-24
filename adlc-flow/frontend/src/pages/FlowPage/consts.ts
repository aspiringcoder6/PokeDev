import { DefaultEdge } from "@/CustomEdges";
import AdlcEdge from "@/CustomEdges/AdlcEdge";
import AdlcStageNode from "@/CustomNodes/AdlcStageNode";
import GenericNode from "@/CustomNodes/GenericNode";
import NoteNode from "@/CustomNodes/NoteNode";

/**
 * Shared ReactFlow node/edge type registrations used by the main canvas
 * (PageComponent).
 */
export const nodeTypes = {
  adlcStageNode: AdlcStageNode,
  genericNode: GenericNode,
  noteNode: NoteNode,
};

export const edgeTypes = {
  adlcEdge: AdlcEdge,
  default: DefaultEdge,
};
