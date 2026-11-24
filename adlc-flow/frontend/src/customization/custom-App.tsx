import { translateUi, useUiLocale } from "@/i18n/ui";
import { lazy, Suspense } from "react";

const App = lazy(() => import("../App"));

export default function CustomApp() {
  useUiLocale();
  return (
    <Suspense
      fallback={
        <div
          role="status"
          className="flex h-screen items-center justify-center text-sm"
        >
          {translateUi("Opening PokeDev…")}
        </div>
      }
    >
      <App />
    </Suspense>
  );
}
