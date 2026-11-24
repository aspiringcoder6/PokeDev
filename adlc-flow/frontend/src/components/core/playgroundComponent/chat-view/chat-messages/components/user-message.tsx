import { translateUi } from "@/i18n/ui";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { chatMessagePropsType } from "@/types/components";
import FilePreviewDisplay from "../../utils/file-preview-display";
import {
  IconCopyOutline16,
  IconCheckOutline16,
} from "../../components/deepseek-icons";

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Format message clock (HH:mm / Aug 20 17:05 / 2025/08/20 17:05) */
function formatMessageClock(timeMs?: number): string {
  const time = timeMs ?? Date.now();
  const d = new Date(time);
  const n = new Date();
  const clock = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  if (
    d.getFullYear() === n.getFullYear() &&
    d.getMonth() === n.getMonth() &&
    d.getDate() === n.getDate()
  ) {
    return clock;
  }
  const monthNames = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
  ];
  if (d.getFullYear() === n.getFullYear()) {
    return `${monthNames[d.getMonth()]} ${d.getDate()} ${clock}`;
  }
  return `${d.getFullYear()}/${pad2(d.getMonth() + 1)}/${pad2(d.getDate())} ${clock}`;
}

function projectUserText(text: string) {
  const re = /(^|\s)([/@][\w-]+)(?=\s|$)/g;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let m: RegExpExecArray | null;

  while ((m = re.exec(text)) !== null) {
    const tokenStart = m.index + (m[1]?.length ?? 0);
    const label = m[2] ?? "";
    if (tokenStart > cursor) {
      parts.push(text.slice(cursor, tokenStart));
    }
    parts.push(
      <span key={tokenStart} className="dsh-ref-chip">
        {label}
      </span>,
    );
    cursor = tokenStart + label.length;
  }

  if (parts.length === 0) return text;
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }
  return <>{parts}</>;
}

export const UserMessage = memo(
  ({ chat, lastMessage }: chatMessagePropsType) => {
    const { t } = useTranslation();
    const [copied, setCopied] = useState(false);

    const chatMessage = chat.message ? chat.message.toString() : "";

    let decodedMessage = chatMessage ?? "";
    try {
      decodedMessage = decodeURIComponent(chatMessage);
    } catch (_e) {
      // ignore decode errors
    }

    const isEmpty = decodedMessage?.trim() === "";
    const hasFiles = chat.files && chat.files.length > 0;

    const handleCopy = () => {
      if (!decodedMessage || copied) return;
      navigator.clipboard.writeText(decodedMessage);
      setCopied(true);
      setTimeout(() => setCopied(false), 1000);
    };

    const timestampMs = chat.timestamp
      ? new Date(chat.timestamp).getTime()
      : undefined;
    const formattedTime = formatMessageClock(timestampMs);

    return (
      <div className="w-full py-2">
        <div
          className="dsh-user-row dsh-user-actions-root"
          data-time-hover-root=""
        >
          <div className="dsh-user-stack">
            {hasFiles && (
              <div className="flex flex-wrap justify-end gap-2 max-w-full">
                {chat.files?.map((file, index) => (
                  <FilePreviewDisplay
                    key={index}
                    file={file}
                    variant="expanded"
                    showDelete={false}
                  />
                ))}
              </div>
            )}
            {(!isEmpty || !hasFiles) && (
              <div className="dsh-user-bubble">
                {isEmpty ? (
                  <span className="text-muted-foreground">
                    {t("input.noInputMessage")}
                  </span>
                ) : (
                  projectUserText(decodedMessage)
                )}
              </div>
            )}
          </div>

          {/* MessageIconActions Row (Clock + Copy Button) */}
          <div className="dsh-actions-row">
            <span className="dsh-time-start">{formattedTime}</span>
            <button
              type="button"
              onClick={handleCopy}
              className="dsh-action-btn"
              title={copied ? translateUi("Copied") : translateUi("Copy")}
              aria-label={copied ? translateUi("Copied") : translateUi("Copy")}
            >
              {copied ? (
                <IconCheckOutline16 size={16} />
              ) : (
                <IconCopyOutline16 size={16} />
              )}
            </button>
          </div>
        </div>
        <div id={lastMessage ? "last-chat-message" : undefined} />
      </div>
    );
  },
);
