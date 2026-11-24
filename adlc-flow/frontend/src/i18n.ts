import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en.json";
import vi from "./locales/vi.json";
import viUi from "./locales/vi-ui.json";

const SUPPORTED_LANGUAGES = [
  "vi",
  "en",
  "de",
  "es",
  "fr",
  "ja",
  "pt",
  "zh-Hans",
] as const;

export const normalizeLanguage = (lang?: string | null): string => {
  if (!lang) return "vi";

  if (
    SUPPORTED_LANGUAGES.includes(lang as (typeof SUPPORTED_LANGUAGES)[number])
  ) {
    return lang;
  }

  const lowerLang = lang.trim().toLowerCase();

  if (["zh-hans", "zh-cn", "zh-sg"].includes(lowerLang)) {
    return "zh-Hans";
  }

  const baseLang = lowerLang.split("-")[0];

  if (
    SUPPORTED_LANGUAGES.includes(
      baseLang as (typeof SUPPORTED_LANGUAGES)[number],
    )
  ) {
    return baseLang;
  }

  return "vi";
};

export const detectedLang = normalizeLanguage(
  localStorage.getItem("languagePreference") || "vi",
);

const i18n = i18next.createInstance();

// i18next hardcodes a Locize promotional message via console.info during init.
// Suppress it by temporarily replacing console.info for the synchronous init call.
const _consoleInfo = console.info.bind(console);
console.info = () => {};
// Tests may replace react-i18next with a partial mock (no initReactI18next);
// only register the plugin when it is actually available.
if (initReactI18next) {
  i18n.use(initReactI18next);
}
i18n.init({
  resources: {
    en: { translation: en, ui: {} },
    vi: { translation: vi, ui: viUi },
  },
  lng: detectedLang,
  fallbackLng: "en",
  returnNull: false,
  returnEmptyString: false,
  interpolation: {
    escapeValue: false,
  },
});
console.info = _consoleInfo;

const updateDocumentLanguage = (language: string) => {
  document.documentElement.lang = language;
};
updateDocumentLanguage(detectedLang);
i18n.on("languageChanged", updateDocumentLanguage);

export async function loadLanguage(lang: string): Promise<void> {
  if (lang === "en") return;
  if (i18n.hasResourceBundle(lang, "translation")) return;
  try {
    const messages = await import(`./locales/${lang}.json`);
    i18n.addResourceBundle(lang, "translation", messages.default);
  } catch {
    // Unknown locale — no bundle file exists. i18next's fallbackLng: "en" takes over.
  }
}

export default i18n;
