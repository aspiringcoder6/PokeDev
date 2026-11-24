import type { Schema } from "hast-util-sanitize";
import { defaultSchema } from "rehype-sanitize";

/**
 * Custom sanitization schema for markdown content
 * Based on GitHub's sanitization rules but optimized for performance
 *
 * Security: Blocks XSS vectors while allowing safe markdown/HTML elements
 * Performance: Uses allowlist approach with minimal processing overhead
 */
export const markdownSanitizeSchema: Schema = {
  ...(defaultSchema || {}),
  attributes: {
    ...(defaultSchema?.attributes || {}),
    // Allow common attributes for styling and structure
    "*": ["className", "id", ...(defaultSchema?.attributes?.["*"] || [])],
    // Allow safe link attributes
    a: ["href", "title", "target", "rel"],
    // Allow image attributes
    img: ["src", "alt", "title", "width", "height"],
    // Allow video attributes (safe subset)
    video: ["src", "controls", "width", "height", "poster"],
    // Allow audio attributes (safe subset)
    audio: ["src", "controls"],
    // Allow code block attributes
    code: ["className"],
    pre: ["className"],
    // Table attributes
    td: ["align", "colSpan", "rowSpan"],
    th: ["align", "colSpan", "rowSpan"],
    // MathJax / MathML / SVG attributes
    svg: ["viewBox", "width", "height", "fill", "xmlns", "role", "aria-hidden", "ariaHidden", "style", "className"],
    path: ["id", "d", "fill", "stroke", "strokeWidth", "strokeLinecap", "strokeLinejoin", "transform"],
    g: ["id", "fill", "stroke", "data-mml-node", "transform"],
    rect: ["x", "y", "width", "height", "fill", "stroke", "transform"],
    circle: ["cx", "cy", "r", "fill", "stroke", "transform"],
    use: ["href", "xlinkHref", "xlink:href", "transform", "x", "y"],
    math: ["xmlns", "display", "alttext"],
    mrow: ["data-mml-node"],
    mi: ["data-mml-node", "mathvariant"],
    mn: ["data-mml-node"],
    mo: ["data-mml-node", "stretchy", "fence", "separator"],
    mfrac: ["data-mml-node", "linethickness"],
    msup: ["data-mml-node"],
    msub: ["data-mml-node"],
    msubsup: ["data-mml-node"],
    msqrt: ["data-mml-node"],
    mroot: ["data-mml-node"],
    mtable: ["data-mml-node"],
    mtr: ["data-mml-node"],
    mtd: ["data-mml-node"],
    mtext: ["data-mml-node"],
  },
  // Remove dangerous protocols.
  //
  // NOTE: this object REPLACES `defaultSchema.protocols` rather than merging
  // with it, so every URL-bearing attribute allowed above must be listed here.
  // `hast-util-sanitize` only protocol-checks attributes that appear in this
  // map ("no protocols defined? then everything is fine"), so an omission here
  // silently turns that attribute into an unguarded URL sink.
  protocols: {
    href: ["http", "https", "mailto"],
    src: ["http", "https"], // Used by img, video, audio
    // `cite` is inherited from defaultSchema.attributes for blockquote/del/ins,
    // and `poster` is allowed on video above. Both were missing here, which
    // dropped the protocol guard upstream provides for `cite` entirely.
    cite: ["http", "https"],
    poster: ["http", "https"],
    longDesc: ["http", "https"],
  },
  // Strip dangerous tags completely
  strip: ["script", "style"],
  // Allow safe HTML tags for markdown rendering
  tagNames: [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "br",
    "hr",
    "strong",
    "em",
    "u",
    "s",
    "del",
    "ins",
    "code",
    "pre",
    "a",
    "img",
    "video",
    "audio",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "blockquote",
    "div",
    "span",
    "sup",
    "sub",
    // MathJax / MathML / SVG tags
    "math",
    "mrow",
    "mi",
    "mn",
    "mo",
    "mfrac",
    "msup",
    "msub",
    "msubsup",
    "msqrt",
    "mroot",
    "mtable",
    "mtr",
    "mtd",
    "mtext",
    "svg",
    "path",
    "g",
    "rect",
    "circle",
    "defs",
    "use",
    "mjx-container",
  ],
};
