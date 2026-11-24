import { translateUi, useUiLocale } from "@/i18n/ui";
import { useEffect, useMemo, useRef, useState, createElement } from "react";
import type { CSSProperties, ReactNode } from "react";
import Markdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import CodeTabsComponent from "@/components/core/codeTabsComponent";
import { preprocessChatMessage } from "@/utils/markdownUtils";
import { markdownSanitizeSchema } from "@/utils/sanitizeSchema";
import { cn } from "@/utils/utils";

import remarkMath from "remark-math";
import katex from "katex";
import "katex/dist/katex.min.css";

// Verbatim styles and DOM to React converters from DeepSeek Harness for KaTeX math rendering
function styleObject(css: string): CSSProperties {
  const style: Record<string, string> = {};
  for (const declaration of css.split(";")) {
    const colon = declaration.indexOf(":");
    if (colon === -1) continue;
    const name = declaration.slice(0, colon).trim();
    const key = name.replace(/-([a-z])/g, (_, letter: string) =>
      letter.toUpperCase(),
    );
    style[key] = declaration.slice(colon + 1).trim();
  }
  return style;
}

function domToReact(node: ChildNode, key: number): ReactNode {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent;
  if (node.nodeType !== Node.ELEMENT_NODE) return null;
  const element = node as Element;
  const props: Record<string, unknown> = { key };
  for (const attribute of element.attributes) {
    if (attribute.name === "class") props["className"] = attribute.value;
    else if (attribute.name === "style")
      props["style"] = styleObject(attribute.value);
    else props[attribute.name] = attribute.value;
  }
  const children = [...element.childNodes].map(domToReact);
  return children.length === 0
    ? createElement(element.localName, props)
    : createElement(element.localName, props, ...children);
}

export function renderTexToReact(
  value: string,
  displayMode: boolean,
): ReactNode {
  let html: string;
  try {
    html = katex.renderToString(value, { displayMode, throwOnError: true });
  } catch (error) {
    try {
      html = katex.renderToString(value, {
        displayMode,
        strict: "ignore",
        throwOnError: false,
      });
    } catch {
      return (
        <span
          className="katex-error"
          style={{ color: "#cc0000" }}
          title={String(error)}
        >
          {value}
        </span>
      );
    }
  }
  const parsed = new DOMParser().parseFromString(html, "text/html");
  return [...parsed.body.childNodes].map(domToReact);
}

const MathRenderer = ({
  children,
  value,
  displayMode,
}: {
  children?: React.ReactNode;
  value?: string;
  displayMode: boolean;
}) => {
  const tex = typeof children === "string" ? children : value || "";
  return <>{renderTexToReact(tex, displayMode)}</>;
};

type SanitizedMarkdownProps = {
  chatMessage: string;
  isEmpty: boolean;
  emptyMessage?: string;
  className?: string;
};

/**
 * Shared component for rendering sanitized markdown content
 * Uses rehype-sanitize to prevent XSS attacks while allowing safe HTML/markdown
 */
export const SanitizedMarkdown = ({
  chatMessage,
  isEmpty,
  emptyMessage,
  className,
}: SanitizedMarkdownProps) => {
  useUiLocale();
  const markdownRef = useRef<HTMLDivElement>(null);
  const [showWarning, setShowWarning] = useState(false);

  // Memoize preprocessing to avoid repeated work on re-renders
  const processedChatMessage = useMemo(() => {
    // Short-circuit for empty messages
    if (!chatMessage || chatMessage.trim() === "") {
      return "";
    }

    // Process the chat message to handle <think> tags and clean up tables
    return preprocessChatMessage(chatMessage);
  }, [chatMessage]);

  // Check if rendered content is empty after sanitization
  useEffect(() => {
    if (markdownRef.current && processedChatMessage && !isEmpty) {
      const textContent = markdownRef.current.textContent?.trim() || "";
      // Check for media/layout elements that don't have text content
      const hasMediaElements =
        markdownRef.current.querySelector("img, hr, video, audio") !== null;
      const hasContent = textContent.length > 0 || hasMediaElements;
      setShowWarning(!hasContent);
    } else {
      setShowWarning(false);
    }
  }, [processedChatMessage, isEmpty]);

  return (
    <div ref={markdownRef} className={className}>
      {showWarning && (
        <div className="text-muted-foreground text-sm p-2 border border-warning bg-warning/30 rounded mb-2">
          {translateUi(
            "⚠️ The response was filtered by security sanitization and cannot be displayed.",
          )}
        </div>
      )}
      {!showWarning && (
        <Markdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSanitizeSchema]]}
          className={cn(
            "dsh-markdown flex w-full max-w-full flex-col",
            isEmpty
              ? "text-muted-foreground"
              : "text-foreground dark:text-[#f9fafb]",
            className,
          )}
          components={{
            math: ({ children, value }: any) => (
              <MathRenderer displayMode={true} value={value}>
                {children}
              </MathRenderer>
            ),
            inlineMath: ({ children, value }: any) => (
              <MathRenderer displayMode={false} value={value}>
                {children}
              </MathRenderer>
            ),
            // Spread first, then pin target/rel, so a raw-HTML anchor that
            // arrives with its own target/rel cannot opt out of noopener.
            // Matches the link handling every other Markdown site here uses.
            a: ({ node, ...props }) => (
              <a {...props} target="_blank" rel="noopener noreferrer">
                {props.children}
              </a>
            ),
            p({ node, ...props }) {
              return <p className="w-fit max-w-full">{props.children}</p>;
            },
            ol({ node, ...props }) {
              return <ol className="max-w-full">{props.children}</ol>;
            },
            ul({ node, ...props }) {
              return <ul className="max-w-full mb-2">{props.children}</ul>;
            },
            pre({ node, ...props }) {
              return <>{props.children}</>;
            },
            hr({ node, ...props }) {
              return (
                <hr className="w-full mt-3 mb-5 border-border" {...props} />
              );
            },
            h3({ node, ...props }) {
              return <h3 className={cn("mt-4", props.className)} {...props} />;
            },
            table: ({ node, ...props }) => {
              return (
                <div className="dsh-table-scroll my-3">
                  <table className="dsh-table">{props.children}</table>
                </div>
              );
            },
            // biome-ignore lint/suspicious/noExplicitAny: pre-existing react-markdown override; proper type cleanup out of scope for this PR
            code: ({ node, className, children, ...props }: any) => {
              let content = children as string;
              if (
                Array.isArray(children) &&
                children.length === 1 &&
                typeof children[0] === "string"
              ) {
                content = children[0] as string;
              }
              if (typeof content === "string") {
                if (content.length) {
                  if (content[0] === "▍") {
                    return <span className="form-modal-markdown-span"></span>;
                  }

                  // Specifically handle <think> tags that were wrapped in backticks
                  if (content === "<think>" || content === "</think>") {
                    return <span>{content}</span>;
                  }
                }

                // react-markdown v8+ removed the `inline` prop. Detect a
                // fenced code block by the presence of either a
                // `language-X` className (hinted block) or multi-line
                // content (unhinted block). Anything else is inline
                // backtick code — rendering it as a `<div>`/`<pre>`
                // CodeTabsComponent inside a markdown `<p>` triggers the
                // 'div cannot be a descendant of p' hydration error.
                const match = /language-(\w+)/.exec(className || "");
                const isMath =
                  className?.includes("math") || (match && match[1] === "math");
                if (isMath) {
                  const isDisplay =
                    className?.includes("math-display") ||
                    (match && match[1] === "math") ||
                    content.includes("\n");
                  return (
                    <MathRenderer displayMode={isDisplay} value={content} />
                  );
                }

                const isBlock =
                  match !== null || (content?.includes("\n") ?? false);

                return isBlock ? (
                  <CodeTabsComponent
                    language={(match && match[1]) || ""}
                    code={String(content).replace(/\n$/, "")}
                  />
                ) : (
                  <code className={className} {...props}>
                    {content}
                  </code>
                );
              }
            },
          }}
        >
          {isEmpty
            ? emptyMessage || ""
            : processedChatMessage
                .replace(
                  /\\\[([\s\S]*?)\\\]/g,
                  (_, math) => `$$\n${math.trim()}\n$$`,
                )
                .replace(
                  /\\\(([\s\S]*?)\\\)/g,
                  (_, math) => `$${math.trim()}$`,
                )}
        </Markdown>
      )}
    </div>
  );
};
