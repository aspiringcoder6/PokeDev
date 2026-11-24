import { useTranslation } from "react-i18next";
import ShadTooltip from "@/components/common/shadTooltipComponent";
import { Button } from "@/components/ui/button";
import { CHAT_UPLOAD_ATTACHMENT_ACCEPT } from "@/constants/file-upload-constants";
import { IconPlusOutline16 } from "../../components/deepseek-icons";

interface UploadFileButtonProps {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  handleFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
  handleButtonClick: () => void;
  isBuilding: boolean;
}

const UploadFileButton = ({
  fileInputRef,
  handleFileChange,
  handleButtonClick,
  isBuilding,
}: UploadFileButtonProps) => {
  const { t } = useTranslation();

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    handleButtonClick();
  };

  return (
    <ShadTooltip
      styleClasses="z-50"
      side="right"
      content={t("chat.attachFileTooltip")}
    >
      <div>
        <input
          disabled={isBuilding}
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={handleFileChange}
          accept={CHAT_UPLOAD_ATTACHMENT_ACCEPT}
        />
        <Button
          disabled={isBuilding}
          className={`h-[28px] w-[28px] rounded-full bg-[#353638] hover:bg-[#434446] text-foreground transition-colors flex items-center justify-center border-0 p-0 ${
            isBuilding ? "opacity-50 cursor-not-allowed" : "cursor-pointer"
          }`}
          onClick={handleClick}
          unstyled
          aria-label={t("chat.attachFileTooltip")}
        >
          <IconPlusOutline16 size={14} />
        </Button>
      </div>
    </ShadTooltip>
  );
};

export default UploadFileButton;
