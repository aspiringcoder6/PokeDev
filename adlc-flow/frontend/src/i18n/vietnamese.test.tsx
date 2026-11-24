jest.unmock("react-i18next");

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { createRef } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter } from "react-router-dom";
import PackageLibrary from "@/features/adlc-workspace/package-library";
import WorkspaceNavigation from "@/features/adlc-workspace/workspace-navigation";
import {
  blockName,
  createLibraryNode,
} from "@/features/adlc-workspace/builder-model";
import {
  REQUEST_EXAMPLES,
  createStudioPlan,
} from "@/features/product-studio/model";
import {
  createVanguardReport,
  VANGUARD_OPTIONS,
} from "@/features/product-studio/vanguard";
import i18n, { loadLanguage, normalizeLanguage } from "@/i18n";
import en from "@/locales/en.json";
import vi from "@/locales/vi.json";
import viUi from "@/locales/vi-ui.json";
import { formatUiStatus, translateUi } from "./ui";

afterEach(async () => {
  cleanup();
  await i18n.changeLanguage("en");
  localStorage.setItem("languagePreference", "en");
});

test("Vietnamese catalog covers every existing key and preserves interpolation and rich-text tags", () => {
  expect(Object.keys(vi).sort()).toEqual(Object.keys(en).sort());
  const protectedParts = (text: string) =>
    text.match(/\{\{[^{}]*\}\}|<\/?\d+>|`+[^`\n]+`+/g) ?? [];
  for (const [key, source] of Object.entries(en)) {
    expect(vi[key as keyof typeof vi].trim()).not.toBe("");
    expect(protectedParts(vi[key as keyof typeof vi])).toEqual(
      protectedParts(source),
    );
  }
  for (const [source, translated] of Object.entries(viUi)) {
    expect(translated.trim()).not.toBe("");
    expect(protectedParts(translated)).toEqual(protectedParts(source));
  }
});

test("regional language preferences normalize while saved languages remain supported", () => {
  expect(normalizeLanguage(null)).toBe("vi");
  expect(normalizeLanguage("vi-VN")).toBe("vi");
  expect(normalizeLanguage(" VI-vn ")).toBe("vi");
  expect(normalizeLanguage("en-US")).toBe("en");
  expect(normalizeLanguage("fr-FR")).toBe("fr");
  expect(normalizeLanguage("zh-CN")).toBe("zh-Hans");
  expect(normalizeLanguage("unsupported")).toBe("vi");
});

test.each([null, "vi-VN", "en", "fr"])(
  "initial language respects preference %s",
  (preference) => {
    if (preference === null) localStorage.removeItem("languagePreference");
    else localStorage.setItem("languagePreference", preference);
    jest.isolateModules(() => {
      const fresh = require("@/i18n").default;
      expect(fresh.language).toBe(
        preference === null || preference === "vi-VN" ? "vi" : preference,
      );
    });
  },
);

test("navigation and document language update immediately in both directions", async () => {
  await loadLanguage("vi");
  await i18n.changeLanguage("vi");
  render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter>
        <WorkspaceNavigation />
      </MemoryRouter>
    </I18nextProvider>,
  );
  expect(screen.getByRole("button", { name: "Dự án" })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Cài đặt workspace" }),
  ).toBeInTheDocument();
  expect(document.documentElement.lang).toBe("vi");
  await act(async () => {
    await i18n.changeLanguage("en");
  });
  expect(screen.getByRole("button", { name: "Projects" })).toBeInTheDocument();
  expect(document.documentElement.lang).toBe("en");
  await act(async () => {
    await i18n.changeLanguage("vi");
  });
  expect(screen.getByRole("button", { name: "Dự án" })).toBeInTheDocument();
});

test("translated status and counts keep wire values and user-provided interpolation intact", async () => {
  await i18n.changeLanguage("vi");
  const status = "WAITING_APPROVAL";
  expect(formatUiStatus(status)).toBe("Chờ phê duyệt");
  expect(status).toBe("WAITING_APPROVAL");
  expect(
    translateUi("Blueprint ready — {{value0}} stage{{value1}} applied", {
      value0: "s",
      value1: "s",
    }),
  ).toContain("s");
  expect(
    translateUi("Blueprint ready — {{value0}} stage{{value1}} applied", {
      value0: 2,
      value1: "s",
    }),
  ).not.toMatch(/s$/);
  expect(
    translateUi("Add {{value0}}", { value0: "My API workflow <test>" }),
  ).toContain("My API workflow <test>");
  await i18n.changeLanguage("en");
  expect(formatUiStatus("CANCEL_REQUESTED")).toBe("CANCEL_REQUESTED");
  expect(formatUiStatus("CANCEL_REQUESTED", true)).toBe("CANCEL REQUESTED");
});

test("package search and creating a requirement work in Vietnamese without changing custom names", async () => {
  await i18n.changeLanguage("vi");
  const onAdd = jest.fn();
  render(
    <I18nextProvider i18n={i18n}>
      <PackageLibrary
        packages={[]}
        loading={false}
        error={false}
        readOnly={false}
        onAdd={onAdd}
        onClose={jest.fn()}
        onRetry={jest.fn()}
        canvas={createRef<HTMLDivElement>()}
      />
    </I18nextProvider>,
  );
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Yêu cầu" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Thêm Yêu cầu" }));
  expect(onAdd).toHaveBeenCalledWith({ type: "requirement" });
  const node = createLibraryNode({ type: "requirement" }, { x: 0, y: 0 });
  expect(node.data.adlcDraft?.kind).toBe("REQUIREMENT");
  expect(node.data.adlcDraft?.name).toBe("Yêu cầu");
  node.data.adlcDraft!.name = "My untranslated project s";
  expect(blockName(node)).toBe("My untranslated project s");
});

test("studio samples follow language changes and retain pagination policy semantics", async () => {
  const englishExample = REQUEST_EXAMPLES[0].text;
  await i18n.changeLanguage("vi");
  expect(REQUEST_EXAMPLES[0].text).not.toBe(englishExample);
  expect(createStudioPlan(REQUEST_EXAMPLES[0].text).scenario).toBe("export");
  const report = createVanguardReport(VANGUARD_OPTIONS[1]);
  expect(
    report.cases.find((item) => item.id === "explicit-page-size")?.finding,
  ).toBe("WARN");
  await i18n.changeLanguage("en");
  expect(REQUEST_EXAMPLES[0].text).toBe(englishExample);
});
