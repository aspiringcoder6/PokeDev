import * as React from "react";
import { createRoot } from "react-dom/client";
import ContractViewer from "@/components/adlc/ContractViewer";
import { copyContract } from "@/components/adlc/ContractViewer/test-fixtures";
import "@/style/index.css";
import RecoveryPreview from "./recovery";

const query = new URLSearchParams(location.search);
const embedded =
  query.get("embedded") === "true" ||
  /^\/contracts\/harness\//.test(location.pathname);
const harness = query.get("host") === "harness";
const recovery = query.get("recovery") === "true";
if (query.get("theme") !== "light")
  document.documentElement.classList.add("dark");
document.body.className = "bg-background text-foreground";
const fixture = copyContract();
type NativePlugin = {
  Pane: React.ComponentType<{ ctx: Record<string, never>; sessionId: string }>;
};
type PreviewWindow = typeof window & {
  __ADLC_CONTRACT_UI__: { baseUrl: string };
  __ModuleLoader__: {
    load: (entry: {
      id: string;
      factory: (require: (id: string) => typeof React) => NativePlugin;
    }) => void;
  };
};
function Preview() {
  const [nativePlugin, setNativePlugin] = React.useState<NativePlugin>();
  React.useEffect(() => {
    if (!harness) return;
    const previewWindow = window as PreviewWindow;
    previewWindow.__ADLC_CONTRACT_UI__ = { baseUrl: location.origin };
    previewWindow.__ModuleLoader__ = {
      load: ({ factory }) => setNativePlugin(() => factory(() => React)),
    };
    const script = document.createElement("script");
    script.type = "module";
    script.src = "/harness-contract-client.js";
    document.body.appendChild(script);
    return () => {
      script.remove();
    };
  }, []);
  if (embedded)
    return (
      <main className="p-4">
        {recovery ? <RecoveryPreview /> : <ContractViewer contract={fixture} />}
      </main>
    );
  return (
    <main className="mx-auto max-w-6xl p-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-widest text-muted-foreground">
            Offline fixture · no API or model calls
          </p>
          <h1 className="mt-1 text-2xl font-semibold">
            {harness ? "Harness Contracts pane" : "ADLC Contract viewer"}
          </h1>
        </div>
        <nav className="flex gap-3 text-sm underline">
          <a href="?host=adlc">ADLC layout</a>
          <a href="?host=harness">Harness pane</a>
          <a href="?theme=light">Light theme</a>
        </nav>
      </header>
      {harness ? (
        <div className="ml-auto h-[820px] w-full max-w-[430px] rounded-lg border bg-background">
          {nativePlugin ? (
            React.createElement(nativePlugin.Pane, {
              ctx: {},
              sessionId: recovery ? "session-h5d" : "session-one",
            })
          ) : (
            <p>Loading native viewer adapter…</p>
          )}
        </div>
      ) : (
        <div className="rounded-xl border bg-background p-6">
          {recovery ? (
            <RecoveryPreview />
          ) : (
            <ContractViewer contract={fixture} />
          )}
        </div>
      )}
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
