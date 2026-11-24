import { translateUi, useUiLocale } from "@/i18n/ui";
import React, { useState, useRef, useEffect, useCallback } from "react";
import css from "./MessageIconActions.module.css";
import {
  IconCopyOutline16,
  IconCheckOutline16,
  IconBranchOutline16,
  IconLikeOutline16,
  IconLikeFill16,
  IconDislikeOutline16,
  IconDislikeFill16,
} from "../../components/deepseek-icons";

export interface MessageIconActionsProps {
  text: string;
  time?: number;
  runMs?: number;
  ttftMs?: number;
  tokensPerSecond?: number;
  clock?: "start" | "end";
  positiveFeedback?: boolean | null;
  onEvaluate?: (evaluation: boolean | null) => void;
  onBranch?: () => void;
  branchUnavailable?: boolean;
  className?: string;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

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

function formatRunDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return minutes > 0 ? `${minutes}m ${pad2(seconds)}s` : `${seconds}s`;
}

function formatLatencySeconds(ms: number): string {
  const s = Math.max(0, ms) / 1000;
  return s < 10 ? String(Math.round(s * 10) / 10) : String(Math.round(s));
}

function formatTokensPerSecond(tps: number): string {
  const clamped = Math.max(0, tps);
  return clamped >= 10
    ? String(Math.round(clamped))
    : String(Math.round(clamped * 10) / 10);
}

export function MessageIconActions({
  text,
  time,
  runMs,
  ttftMs,
  tokensPerSecond,
  clock = "end",
  positiveFeedback,
  onEvaluate,
  onBranch,
  branchUnavailable = false,
  className,
}: MessageIconActionsProps) {
  useUiLocale();
  const [copied, setCopied] = useState(false);
  const copyPending = useRef(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      copyPending.current = false;
      if (copyTimer.current !== null) clearTimeout(copyTimer.current);
    },
    [],
  );

  const onCopy = useCallback(() => {
    if (copied || copyPending.current || !text) return;
    copyPending.current = true;
    navigator.clipboard.writeText(text).then(() => {
      copyPending.current = false;
      setCopied(true);
      copyTimer.current = setTimeout(() => {
        copyTimer.current = null;
        setCopied(false);
      }, 1000);
    });
  }, [copied, text]);

  const clockEl =
    time === undefined ? null : (
      <span className={clock === "start" ? css.timeStart : css.timeEnd}>
        {formatMessageClock(time)}
        {runMs !== undefined && runMs > 0 && (
          <>
            {" "}
            <span className={css.runTimeDot} aria-hidden>
              ·
            </span>{" "}
            {translateUi("Ran for")} {formatRunDuration(runMs)}
          </>
        )}
        {ttftMs !== undefined && (
          <>
            {" "}
            <span className={css.runTimeDot} aria-hidden>
              ·
            </span>{" "}
            TTFT {formatLatencySeconds(ttftMs)}s
          </>
        )}
        {tokensPerSecond !== undefined && tokensPerSecond > 0 && (
          <>
            {" "}
            <span className={css.runTimeDot} aria-hidden>
              ·
            </span>{" "}
            {formatTokensPerSecond(tokensPerSecond)} tok/s
          </>
        )}
      </span>
    );

  return (
    <div
      className={
        className === undefined ? css.actions : `${css.actions} ${className}`
      }
    >
      {clock === "start" ? clockEl : null}

      {/* 1. Copy Action Button */}
      <button
        type="button"
        className={css.action}
        aria-label={copied ? translateUi("Copied") : translateUi("Copy")}
        title={copied ? translateUi("Copied") : translateUi("Copy")}
        onClick={onCopy}
      >
        {copied ? <IconCheckOutline16 /> : <IconCopyOutline16 />}
      </button>

      {/* 2. Like Action Button */}
      {onEvaluate && (
        <button
          type="button"
          className={`${css.action} ${positiveFeedback === true ? css.actionActiveLike : ""}`}
          aria-label={translateUi("Good response")}
          title={translateUi("Good response")}
          onClick={() => onEvaluate(positiveFeedback === true ? null : true)}
        >
          {positiveFeedback === true ? (
            <IconLikeFill16 />
          ) : (
            <IconLikeOutline16 />
          )}
        </button>
      )}

      {/* 3. Dislike Action Button */}
      {onEvaluate && (
        <button
          type="button"
          className={`${css.action} ${positiveFeedback === false ? css.actionActiveDislike : ""}`}
          aria-label={translateUi("Bad response")}
          title={translateUi("Bad response")}
          onClick={() => onEvaluate(positiveFeedback === false ? null : false)}
        >
          {positiveFeedback === false ? (
            <IconDislikeFill16 />
          ) : (
            <IconDislikeOutline16 />
          )}
        </button>
      )}

      {/* 4. Branch / Regenerate Action Button */}
      <button
        type="button"
        className={css.action}
        aria-label={translateUi("Branch / Regenerate")}
        aria-disabled={branchUnavailable || undefined}
        data-unavailable={branchUnavailable || undefined}
        title={translateUi("Branch / Regenerate")}
        onClick={branchUnavailable ? undefined : onBranch}
      >
        <IconBranchOutline16 />
      </button>

      {clock === "end" ? clockEl : null}
    </div>
  );
}
