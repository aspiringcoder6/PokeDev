import { useEffect, useRef, useState } from "react";
import { IconThinkOutline14 } from "../../components/deepseek-icons";
import { ChevronDown } from "lucide-react";

function firstLine(text: string): string {
  const newline = text.indexOf("\n");
  return newline === -1 ? text : text.slice(0, newline);
}

function latestLine(text: string): string {
  const visible = text.trimEnd();
  const newline = visible.lastIndexOf("\n");
  return newline === -1 ? visible : visible.slice(newline + 1);
}

export interface ReasoningRowProps {
  text: string;
  running?: boolean;
  duration?: number;
}

export function ReasoningRow({ text, running = false, duration }: ReasoningRowProps) {
  const [expanded, setExpanded] = useState(false);
  const summaryRef = useRef<HTMLSpanElement>(null);
  const summary = running ? latestLine(text) : firstLine(text);

  useEffect(() => {
    const element = summaryRef.current;
    if (element === null) return;
    element.scrollLeft = running ? element.scrollWidth - element.clientWidth : 0;
  }, [running, summary]);

  const titleText = running
    ? "Thinking..."
    : duration && duration > 0
    ? `Thought for ${Math.round(duration)}s`
    : "Thought";

  return (
    <div className="dsh-reasoning-root" data-state={running ? "running" : "ok"} data-open={expanded || undefined}>
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        className="dsh-reasoning-row group flex items-center h-6 w-full text-left bg-transparent border-none p-0 cursor-pointer overflow-hidden relative"
      >
        {/* Leading icon container (16x16) at the START of the row, before title */}
        <div className="dsh-reasoning-leading relative w-4 h-4 flex items-center justify-center mr-1.5 flex-shrink-0 text-[#81858c]">
          {expanded ? (
            <ChevronDown size={14} className="text-[#b4b7bd]" />
          ) : (
            <>
              <span className="inline-flex transition-opacity duration-100 ease-in-out group-hover:opacity-0">
                <IconThinkOutline14 size={14} />
              </span>
              <span className="absolute inset-0 flex items-center justify-center opacity-0 transition-opacity duration-100 ease-in-out group-hover:opacity-100 text-[#b4b7bd]">
                <ChevronDown size={14} />
              </span>
            </>
          )}
        </div>

        {/* Title: 'Thinking...' or 'Thought for 2s' */}
        <span className="dsh-reasoning-title text-[14px] leading-[24px] font-normal text-[#b4b7bd] flex-none">
          {titleText}
        </span>

        {/* Separator dot and streaming/settled summary */}
        {summary && !expanded && (
          <>
            <span className="dsh-reasoning-separator flex-none w-[2px] h-[2px] mx-2 rounded-[1px] bg-[#52525b]" aria-hidden />
            <span ref={summaryRef} className="dsh-reasoning-summary min-w-0 overflow-hidden flex-1 text-[#81858c] text-[14px] leading-[24px] truncate whitespace-nowrap">
              {summary}
            </span>
          </>
        )}
      </button>
      {expanded && (
        <div className="dsh-reasoning-body pl-5.5 py-1 text-[#81858c] text-[14px] leading-[24px] whitespace-pre-wrap break-words">
          {text}
        </div>
      )}
    </div>
  );
}
