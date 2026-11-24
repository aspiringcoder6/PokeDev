import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import AlertDropdown from "@/alerts/alertDropDown";
import VAIPlatformLogo from "@/assets/PokeDevLogo.svg?react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import ModelProviderCount from "@/components/common/modelProviderCountComponent";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import CustomAccountMenu from "@/customization/components/custom-AccountMenu";
import { CustomOrgSelector } from "@/customization/components/custom-org-selector";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import useTheme from "@/customization/hooks/use-custom-theme";
import useAlertStore from "@/stores/alertStore";
import useFlowStore from "@/stores/flowStore";
import { isAdlcBlueprint } from "@/utils/adlc-blueprint";
import FlowMenu from "./components/FlowMenu";

export default function AppHeader(): JSX.Element {
  const { t } = useTranslation();
  const notificationCenter = useAlertStore((state) => state.notificationCenter);
  const navigate = useCustomNavigate();
  const location = useLocation();
  const blueprint = useFlowStore((state) => isAdlcBlueprint(state.currentFlow));
  const [activeState, setActiveState] = useState<"notifications" | null>(null);
  const notificationRef = useRef<HTMLButtonElement | null>(null);
  const notificationContentRef = useRef<HTMLDivElement | null>(null);
  useTheme();

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      const isNotificationButton = notificationRef.current?.contains(target);
      const isNotificationContent =
        notificationContentRef.current?.contains(target);

      if (!isNotificationButton && !isNotificationContent) {
        setActiveState(null);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const getNotificationBadge = () => {
    const baseClasses = "absolute h-1 w-1 rounded-full bg-destructive";
    return notificationCenter
      ? `${baseClasses} right-[0.3rem] top-[5px]`
      : "hidden";
  };

  return (
    <header
      className="z-10 flex h-[48px] w-full shrink-0 items-center justify-between gap-3 border-b bg-card pr-5 pl-3"
      data-testid="app-header"
    >
      {/* Left Section */}
      <div
        className={`z-30 flex shrink-0 items-center gap-2`}
        data-testid="header_left_section_wrapper"
      >
        <Button
          unstyled
          onClick={() => navigate("/")}
          className="mr-1 flex h-9 items-center gap-2 rounded-md px-1.5 text-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          data-testid="icon-ChevronLeft"
          aria-label={t("header.home")}
        >
          <VAIPlatformLogo className="h-8 w-8 rounded-md" aria-hidden="true" />
          <span className="hidden text-base font-semibold tracking-tight sm:inline">
            <span className="text-primary">vAI</span>Platform
          </span>
        </Button>
        <CustomOrgSelector />
      </div>

      {/* Middle Section */}
      {location.pathname.includes("/flow/") && !blueprint && (
        <div className="absolute left-1/2 -translate-x-1/2">
          <FlowMenu />
        </div>
      )}

      {/* Right Section */}
      <div
        className={`relative left-3 z-30 flex shrink-0 items-center gap-3`}
        data-testid="header_right_section_wrapper"
      >
        {false && <ModelProviderCount />}
        <AlertDropdown
          notificationRef={notificationContentRef}
          onClose={() => setActiveState(null)}
        >
          <ShadTooltip
            content={t("header.notifications")}
            side="bottom"
            ariaDescribedBy={undefined}
          >
            <AlertDropdown onClose={() => setActiveState(null)}>
              <Button
                ref={notificationRef}
                unstyled
                aria-label={t("header.notifications")}
                onClick={() =>
                  setActiveState((prev) =>
                    prev === "notifications" ? null : "notifications",
                  )
                }
                data-testid="notification_button"
              >
                <div className="hit-area-hover group relative items-center rounded-md px-2 py-2 text-muted-foreground">
                  <span className={getNotificationBadge()} />
                  <ForwardedIconComponent
                    name="Bell"
                    className={`side-bar-button-size h-4 w-4 ${
                      activeState === "notifications"
                        ? "text-primary"
                        : "text-muted-foreground group-hover:text-primary"
                    }`}
                    strokeWidth={2}
                  />
                  <span className="hidden whitespace-nowrap">
                    {t("header.notificationsLabel")}
                  </span>
                </div>
              </Button>
            </AlertDropdown>
          </ShadTooltip>
        </AlertDropdown>
        <Separator
          orientation="vertical"
          className="my-auto h-7 dark:border-border"
        />

        <div className="flex">
          <CustomAccountMenu />
        </div>
      </div>
    </header>
  );
}
