import { translateUi } from "@/i18n/ui";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ContentBlockDisplay } from "@/components/core/chatComponents/ContentBlockDisplay";
import HumanInputCard from "@/components/core/chatComponents/HumanInputCard";
import { findHumanInputContent } from "@/controllers/API/agui/human-input-card";
import { useUpdateMessage } from "@/controllers/API/queries/messages";
import { CustomMarkdownField } from "@/customization/components/custom-markdown-field";
import useAlertStore from "@/stores/alertStore";
import useFlowStore from "@/stores/flowStore";
import useFlowsManagerStore from "@/stores/flowsManagerStore";
import type { chatMessagePropsType } from "@/types/components";
import { useMessageDuration } from "../hooks/use-message-duration";
import { useStreamingMessage } from "../hooks/use-streaming-message";
import {
  excludeHumanInputBlocks,
  getContentBlockLoadingState,
  getContentBlockState,
  resolveContentBlockLayout,
} from "../utils/content-blocks";
import { convertFiles } from "../utils/convert-files";
import EditMessageField from "./edit-message-field";
import { ReasoningRow } from "./reasoning-row";
import { MessageIconActions } from "./MessageIconActions";

export const BotMessage = memo(
  ({ chat, lastMessage, updateChat, playgroundPage }: chatMessagePropsType) => {
    const { t } = useTranslation();
    const setErrorData = useAlertStore((state) => state.setErrorData);
    const [editMessage, setEditMessage] = useState(false);
    const isBuilding = useFlowStore((state) => state.isBuilding);
    const buildStartTime = useFlowStore((state) => state.buildStartTime);
    const buildDuration = useFlowStore((state) => state.buildDuration);
    const flow_id = useFlowsManagerStore((state) => state.currentFlowId);

    const isAudioMessage = chat.category === "audio";

    const { chatMessage: decodedMessage, isStreaming } = useStreamingMessage({
      chat,
      isBuilding,
      updateChat,
    });

    const isEmpty = decodedMessage?.trim() === "";
    const chatMessage = chat.message ? chat.message.toString() : "";
    const humanInputContent = findHumanInputContent(chat.content_blocks);
    const hasContentBlocks = (chat.content_blocks?.length ?? 0) > 0;
    const hasRenderableContent = (chat.content_blocks ?? []).some((block) =>
      (block?.contents ?? []).some(
        (content) => (content as { type?: string })?.type === "tool_use",
      ),
    );
    const isContentlessText =
      chatMessage.trim() === "" || chatMessage.trim() === "[]";
    const isBlankPlaceholder =
      chat.properties?.state === "partial" &&
      isContentlessText &&
      !hasRenderableContent &&
      !humanInputContent &&
      !isAudioMessage &&
      (chat.files?.length ?? 0) === 0 &&
      !isStreaming &&
      (!isBuilding || !lastMessage);

    const { mutate: updateMessageMutation } = useUpdateMessage();

    const handleEditMessage = (message: string) => {
      updateMessageMutation(
        {
          message: {
            id: chat.id,
            files: convertFiles(chat.files),
            sender_name: chat.sender_name ?? "AI",
            text: message,
            sender: translateUi("Machine"),
            flow_id,
            session_id: chat.session ?? "",
          },
          refetch: true,
        },
        {
          onSuccess: () => {
            updateChat?.(chat, message);
            setEditMessage(false);
          },
          onError: () => {
            setErrorData({
              title: t("errors.updatingMessages"),
            });
          },
        },
      );
    };

    const handleEvaluateAnswer = (evaluation: boolean | null) => {
      updateMessageMutation(
        {
          message: {
            ...chat,
            files: convertFiles(chat.files),
            sender_name: chat.sender_name ?? "AI",
            text: chat.message.toString(),
            sender: "Machine",
            flow_id,
            session_id: chat.session ?? "",
            properties: {
              ...chat.properties,
              state: chat.properties?.state as
                | "complete"
                | "partial"
                | undefined,
              positive_feedback: evaluation,
            },
          },
        },
        {
          onError: () => {
            setErrorData({
              title: t("errors.updatingMessages"),
            });
          },
        },
      );
    };

    const editedFlag = chat.edit ? (
      <div className="mt-2 text-xs text-muted-foreground text-right">
        (Edited)
      </div>
    ) : null;

    const { displayTime: liveDisplayTime } = useMessageDuration({
      lastMessage,
      isBuilding,
      buildStartTime,
      buildDuration,
    });

    const backendDuration =
      typeof chat.properties?.build_duration === "number" &&
      chat.properties.build_duration > 0
        ? chat.properties.build_duration
        : typeof chat.properties?.duration === "number" &&
            chat.properties.duration > 0
          ? chat.properties.duration
          : undefined;

    const runMs =
      backendDuration !== undefined
        ? backendDuration > 300000
          ? Math.round(backendDuration / 1000)
          : backendDuration
        : isBuilding && lastMessage && buildStartTime
          ? Math.max(0, Date.now() - buildStartTime)
          : liveDisplayTime > 0 && liveDisplayTime < 300000
            ? liveDisplayTime
            : undefined;

    const displayTimeSec = runMs ? runMs / 1000 : 0;

    const { displayedContentBlocks, showBubbleBody } =
      resolveContentBlockLayout(
        excludeHumanInputBlocks(chat.content_blocks ?? []),
        chat.message?.toString(),
        Boolean(editMessage),
      );

    if (isBlankPlaceholder) return null;

    const thinkMatch = decodedMessage.match(/<think>([\s\S]*?)(?:<\/think>|$)/);
    const thinkText = chat.thought || (thinkMatch ? thinkMatch[1].trim() : "");
    const cleanMessageText = decodedMessage
      .replace(/<think>[\s\S]*?<\/think>/g, "")
      .trim();

    const timestampMs = chat.timestamp
      ? new Date(chat.timestamp).getTime()
      : undefined;
    const totalTokens = chat.properties?.usage?.total_tokens;
    const outputTokens = chat.properties?.usage?.output_tokens ?? totalTokens;
    const tps =
      displayTimeSec > 0 && outputTokens && displayTimeSec > 0
        ? outputTokens / displayTimeSec
        : undefined;
    const ttftMs =
      (chat.properties as any)?.ttft_ms ??
      (displayTimeSec > 0
        ? Math.min(displayTimeSec * 1000 * 0.25, 1300)
        : undefined);

    const isBuildingActive = Boolean(isBuilding && lastMessage);
    const isMessageActive = Boolean(
      (isBuildingActive ||
        isStreaming ||
        chat.properties?.state === "partial") &&
        lastMessage,
    );
    const isThinkingActive = Boolean(
      isMessageActive && !decodedMessage.includes("</think>"),
    );

    return (
      <>
        <div className="w-full word-break-break-word mt-2">
          <div
            className="group relative flex w-full flex-col gap-2 rounded-md px-0 py-2"
            data-time-hover-root=""
          >
            <div className="flex w-full items-start gap-0">
              <div className="flex w-full flex-col min-w-0">
                {humanInputContent && (
                  <div className="mt-2">
                    <HumanInputCard content={humanInputContent} />
                  </div>
                )}

                {/* Content Blocks / Tool Calls */}
                {(displayedContentBlocks.length > 0 || isBuildingActive) && (
                  <ContentBlockDisplay
                    playgroundPage={playgroundPage}
                    contentBlocks={displayedContentBlocks}
                    isLoading={getContentBlockLoadingState(
                      chat,
                      isBuilding,
                      lastMessage,
                    )}
                    state={getContentBlockState(chat, isBuilding, lastMessage)}
                    chatId={chat.id}
                    hideHeader={true}
                  />
                )}

                {/* DeepSeek Harness Reasoning Disclosure (<think> extraction) */}
                {thinkText ? (
                  <ReasoningRow
                    text={thinkText}
                    running={isThinkingActive}
                    duration={displayTimeSec}
                  />
                ) : isMessageActive && (isEmpty || isContentlessText) ? (
                  <ReasoningRow text="Thinking..." running={true} />
                ) : null}

                {/* Main Message Text Render */}
                {(showBubbleBody || cleanMessageText !== "") &&
                  cleanMessageText && (
                    <div className="form-modal-chat-text-position flex-grow mt-1">
                      <div className="form-modal-chat-text">
                        <div className="flex w-full flex-col">
                          <div
                            className="flex w-full flex-col dark:text-[#f9fafb] text-[16px] leading-[26px]"
                            data-testid="div-chat-message"
                          >
                            <div
                              data-testid={`chat-message-${chat.sender_name}-${chatMessage}`}
                              className="flex w-full flex-col"
                            >
                              <div className="w-full">
                                {editMessage ? (
                                  <EditMessageField
                                    key={`edit-message-${chat.id}`}
                                    message={cleanMessageText}
                                    onEdit={handleEditMessage}
                                    onCancel={() => setEditMessage(false)}
                                  />
                                ) : (
                                  <CustomMarkdownField
                                    isAudioMessage={isAudioMessage}
                                    chat={chat}
                                    isEmpty={
                                      isEmpty &&
                                      !isStreaming &&
                                      !hasContentBlocks
                                    }
                                    chatMessage={cleanMessageText}
                                    editedFlag={editedFlag}
                                  />
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                {/* DeepSeek Harness TurnStatus ('Deep diving...') */}
                {isMessageActive && (
                  <div
                    className="dsh-turn-status my-1.5"
                    role="status"
                    aria-live="polite"
                  >
                    {translateUi("Deep diving...")}
                    {displayTimeSec >= 15 && (
                      <span className="dsh-turn-status-clock" aria-hidden>
                        {Math.floor(displayTimeSec / 60) > 0
                          ? `${Math.floor(displayTimeSec / 60)}m ${String(Math.floor(displayTimeSec % 60)).padStart(2, "0")}s`
                          : `${Math.floor(displayTimeSec)}s`}
                      </span>
                    )}
                  </div>
                )}

                {/* DeepSeek Harness MessageIconActions */}
                {!editMessage && !isBuilding && (
                  <div className="mt-2 flex items-center">
                    <MessageIconActions
                      text={cleanMessageText}
                      time={timestampMs}
                      runMs={runMs}
                      ttftMs={ttftMs}
                      tokensPerSecond={tps}
                      clock="end"
                      positiveFeedback={chat.properties?.positive_feedback}
                      onEvaluate={handleEvaluateAnswer}
                      onBranch={() => {
                        // Branch callback
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
        <div id={lastMessage ? "last-chat-message" : undefined} />
      </>
    );
  },
);
