import { translateUi, useUiLocale } from "@/i18n/ui";
import { MorphingMenu } from "@/components/ui/morphing-menu";

export default function ImportButtonComponent({
  variant = "large",
}: {
  variant?: "large" | "small";
}) {
  useUiLocale();
  const items = [
    {
      icon: "GoogleDrive",
      label: translateUi("Drive"),
      onClick: () => {
        // Handle Google Drive click
      },
    },
    {
      icon: "OneDrive",
      label: translateUi("OneDrive"),
      onClick: () => {
        // Handle OneDrive click
      },
    },
    {
      icon: "AWSInverted",
      label: translateUi("S3 Bucket"),
      onClick: () => {
        // Handle S3 click
      },
    },
  ];

  return (
    <MorphingMenu variant={variant} trigger="Import from..." items={items} />
  );
}
