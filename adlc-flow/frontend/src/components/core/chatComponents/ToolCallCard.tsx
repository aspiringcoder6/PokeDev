import { translateUi, useUiLocale } from "@/i18n/ui";
import { useEffect, useState } from "react";
import {
  formatTime,
  formatToolTitle,
} from "@/components/core/playgroundComponent/chat-view/chat-messages/utils/format";
import type { ToolContent } from "@/types/chat";
import { cn } from "@/utils/utils";
import { IconSparkle16 } from "@/components/core/playgroundComponent/chat-view/components/deepseek-icons";
import { ChevronDown } from "lucide-react";
import ContentDisplay from "./ContentDisplay";
import { getToolStatus } from "./toolStatus";

export function ToolCallCard({
  content,
  chatId,
  playgroundPage,
}: {
  content: ToolContent;
  chatId: string;
  playgroundPage?: boolean;
}) {
  useUiLocale();
  const status = getToolStatus(content);
  const isRunning = status === "running";

  const rawTitle = content.header?.title || content.name || translateUi("Tool");
  const toolTitle =
    typeof rawTitle === "string" ? formatToolTitle(rawTitle) : rawTitle;
  const toolDuration = content.duration ?? 0;
  const itemKey = chatId;

  const [expanded, setExpanded] = useState(false);

  // Auto-expand on running state transition
  useEffect(() => {
    if (isRunning) {
      setExpanded(true);
    }
  }, [isRunning]);

  const displaySummary = isRunning
    ? translateUi("Deep diving into {{value0}}...", { value0: toolTitle })
    : status === "error"
      ? translateUi("Failed")
      : translateUi("Ran {{value0}}", { value0: toolTitle });

  return (
    <div
      className="dsh-reasoning-root my-1.5"
      data-variant="tool"
      data-state={isRunning ? "running" : status}
    >
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="dsh-reasoning-row"
      >
        <div className="dsh-reasoning-leading flex items-center gap-1.5">
          <IconSparkle16
            size={14}
            className={cn(
              isRunning ? "text-[#679efe] animate-pulse" : "text-[#81858c]",
            )}
          />
        </div>
        <span
          className={cn(
            "dsh-reasoning-title font-medium text-[14px] leading-[24px]",
            isRunning ? "text-[#679efe]" : "text-[#f9fafb]",
          )}
        >
          {isRunning ? translateUi("Deep diving...") : toolTitle}
        </span>
        <ChevronDown
          size={14}
          className={cn(
            "dsh-reasoning-chevron transition-transform duration-200 text-[#81858c]",
            expanded ? "rotate-180" : "",
          )}
        />
        {!expanded && (
          <>
            <span className="dsh-reasoning-separator" aria-hidden />
            <span
              className={cn(
                "dsh-reasoning-summary font-normal text-[14px] leading-[24px]",
                isRunning ? "text-[#679efe]" : "text-[#81858c]",
                status === "error" && "text-[#ef4444]",
              )}
            >
              {displaySummary}
            </span>
          </>
        )}
        {toolDuration > 0 && !isRunning && (
          <span className="ml-auto text-xs text-[#81858c]">
            {formatTime(toolDuration, true)}
          </span>
        )}
      </button>
      {expanded && (
        <div className="dsh-reasoning-body mt-1 rounded-lg border border-white/10 bg-[#151517] p-3 text-xs text-[#f9fafb]">
          <ContentDisplay
            content={content}
            chatId={chatId}
            playgroundPage={playgroundPage}
          />
        </div>
      )}
    </div>
  );
}
