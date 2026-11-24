import { translateUi, useUiLocale } from "@/i18n/ui";
import {
  BookOpen,
  ChevronRight,
  Keyboard,
  MessageSquare,
  SlidersHorizontal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useAdlcNodePackages } from "@/hooks/adlc/use-adlc-node-packages";
import { useTranslation } from "react-i18next";
import "@/i18n";

export default function WorkspaceSettingsPage() {
  useUiLocale();
  const navigate = useCustomNavigate();
  const packages = useAdlcNodePackages();
  const links = [
    {
      label: "Slack & Workloop",
      hint: "Kết nối bot hiện có để hỏi đáp và soạn tài liệu",
      path: "/settings/integrations",
      icon: MessageSquare,
    },
    {
      label: translateUi("Appearance and account"),
      hint: translateUi("Theme, preferences, and account details"),
      path: "/settings/general",
      icon: SlidersHorizontal,
    },
    {
      label: translateUi("Keyboard shortcuts"),
      hint: translateUi("Shortcuts for working with the app"),
      path: "/settings/shortcuts",
      icon: Keyboard,
    },
    {
      label: translateUi("Package library"),
      hint: translateUi(
        "Available packages and planned lifecycle capabilities",
      ),
      path: "/library",
      icon: BookOpen,
    },
  ];
  return (
    <main className="h-full w-full overflow-auto p-5 lg:p-8">
      <div className="mx-auto max-w-3xl space-y-6">
        <header>
          <p className="mb-2 text-xs font-medium text-primary">
            {translateUi("PokeDev · Workspace")}
          </p>
          <h1 className="text-2xl font-semibold">{translateUi("Settings")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {translateUi(
              "Preferences and the resources used by your workflows.",
            )}
          </p>
        </header>
        <section className="overflow-hidden rounded-xl border bg-card">
          {links.map((link) => (
            <Button
              key={link.path}
              unstyled
              onClick={() => navigate(link.path)}
              className="flex w-full items-center gap-3 border-b px-5 py-5 text-left last:border-0 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <link.icon size={18} className="text-primary" />
              <span className="flex-1">
                <span className="block text-sm font-medium">{link.label}</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  {link.hint}
                </span>
              </span>
              <ChevronRight size={15} />
            </Button>
          ))}
        </section>
        <section className="space-y-3 rounded-xl border bg-card p-5">
          <h2 className="text-sm font-semibold">
            {translateUi("Execution setup")}
          </h2>
          <p className="text-xs leading-6 text-muted-foreground">
            {packages.isLoading
              ? translateUi("Checking package access…")
              : packages.isError
                ? translateUi("Package access could not be loaded.")
                : translateUi(
                    "{{value0}} published package versions are available to your account.",
                    {
                      value0:
                        packages.data?.filter(
                          (p) => p.lifecycle_status !== "DEPRECATED",
                        ).length ?? 0,
                    },
                  )}{" "}
            {translateUi(
              "Package access and runtime readiness are separate. Runtime references, capabilities, repository scope, and execution limits are checked by the server when a plan is resolved.",
            )}
          </p>
          <p className="text-xs leading-6 text-muted-foreground">
            {translateUi(
              "Members use permitted project configuration. An administrator prepares runtime connections and policy. The wider team membership and invitation features remain planned.",
            )}
          </p>
          <details className="border-t pt-3">
            <summary className="cursor-pointer text-xs font-medium">
              {translateUi("Advanced configuration")}
            </summary>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigate("/settings/model-providers")}
              >
                {translateUi("Model connections")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigate("/settings/global-variables")}
              >
                {translateUi("Shared variables")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigate("/settings/api-keys")}
              >
                {translateUi("API access")}
              </Button>
            </div>
          </details>
        </section>
      </div>
    </main>
  );
}
