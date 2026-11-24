/**
 * Pre-built demo example for the Blueprint Request Dialog.
 *
 * The requirement string is pre-filled into the dialog textarea. The user
 * can still edit, clear, or replace the text before submitting — this is
 * just a convenient starting point for demos and quick exploration.
 *
 * The example is built by a factory function so that i18n.t runs during
 * render (after the language bundle has loaded) instead of at module
 * evaluation time.
 */

import i18n from "@/i18n";

export type AdlcDemoExample = {
  /** Stable id used as React key and for analytics. */
  id: string;
  /** Short label shown in the picker menu. */
  label: string;
  /** One-line description shown beneath the label. */
  description: string;
  /** Lucide icon name (matches ForwardedIconComponent's catalogue). */
  icon: string;
  /** The full requirement text pre-filled into the textarea. */
  requirement: string;
  /** Optional extra instructions pre-filled into the secondary textarea. */
  instructions?: string;
};

/**
 * Heart App — a tiny frontend demo.
 *
 * Single HTML file with a clickable red heart that reveals "Hello World!".
 * Chosen as the default demo because it is:
 * - Practical (real frontend development)
 * - Simple (one file, ~50 lines)
 * - Verifiable (open in browser to see)
 * - Interactive (click handler)
 * - Hard to fail (no build tools, no dependencies)
 */
export function heartAppExample(): AdlcDemoExample {
  return {
    id: "heart-app",
    label: i18n.t("adlc.demo.heartApp"),
    description: i18n.t("adlc.demo.heartDesc"),
    icon: "Heart",
    requirement: `Create a single HTML file \`index.html\` for a simple frontend website.

Requirements:
1. Display a heart shape in the center of the page (use CSS, not image).
2. The heart must be RED (main color theme of the website).
3. When the user CLICKS on the heart, show a message 'Hello World!' below or near the heart.
4. The page should have a clean, centered layout.
5. Use only HTML, CSS, and vanilla JavaScript (no frameworks, no build tools).
6. The file must work when opened directly in a browser (file:// protocol).

Do not create any other files. Do not modify any existing files.`,
    instructions:
      "Keep the implementation minimal — one file, inline CSS/JS, no external resources.",
  };
}
