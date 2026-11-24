import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

/** Translate application copy without changing API fields or user-authored text. */
export function translateUi(
  source: string,
  values?: Record<string, unknown>,
): string {
  const interpolation = { ...values };
  if (i18n.language.startsWith("vi")) {
    for (const [key, value] of Object.entries(interpolation)) {
      if (
        (value === "s" || value === "es") &&
        new RegExp(
          `\\b(?:task|stage|file|run|result|item|version|attempt|check|session|branch)\\{\\{${key}\\}\\}`,
        ).test(source)
      ) {
        interpolation[key] = "";
      }
    }
  }
  return i18n.t(source, {
    ...interpolation,
    ns: "ui",
    keySeparator: false,
    nsSeparator: false,
    defaultValue: source,
  }) as string;
}

/** Subscribe screens whose copy uses the standalone translator to language changes. */
export function useUiLocale(): string {
  return useTranslation().i18n.language;
}

export function getUiLanguage(): string {
  return i18n.language === "vi" ? "vi-VN" : i18n.language;
}

export function formatUiDateTime(value: string | number | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return translateUi("Unknown");
  return date.toLocaleString(getUiLanguage());
}

/** Localize displayed state labels while preserving their wire values. */
export function formatUiStatus(value: string, humanize = false): string {
  const display = humanize ? value.replaceAll("_", " ") : value;
  return i18n.t(value.toUpperCase().replaceAll(" ", "_"), {
    ns: "ui",
    keySeparator: false,
    nsSeparator: false,
    defaultValue: display,
  }) as string;
}
