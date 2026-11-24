import { Square } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import useFlowStore from "@/stores/flowStore";
import type { FilePreviewType } from "@/types/components";
import { cn } from "@/utils/utils";
import { IconSendOutline16 } from "../../components/deepseek-icons";

const BUTTON_STATES = {
  NO_INPUT: "bg-primary text-primary-foreground opacity-40 cursor-default",
  DEFAULT: "bg-primary text-primary-foreground hover:bg-primary-hover cursor-pointer",
};

type ButtonSendWrapperProps = {
  send: () => void;
  noInput: boolean;
  chatValue: string;
  files: FilePreviewType[];
  isBuilding?: boolean;
};

const ButtonSendWrapper = ({
  send,
  noInput,
  chatValue,
  files,
  isBuilding,
}: ButtonSendWrapperProps) => {
  const { t } = useTranslation();
  const stopBuilding = useFlowStore((state) => state.stopBuilding);
  const isLoading = files.some((file) => file.loading);
  const isEmpty = (!chatValue || chatValue.trim() === "") && files.length === 0;
  const isDisabled = isLoading || (isEmpty && !isBuilding) || noInput;

  const getButtonState = () => {
    if (isDisabled && !isBuilding) return BUTTON_STATES.NO_INPUT;
    return BUTTON_STATES.DEFAULT;
  };

  const buttonClasses = cn("form-modal-send-button", getButtonState());
  const buttonLabel = isBuilding
    ? t("flowBuild.stop")
    : t("playground.sendButton");

  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();

    if (isBuilding) {
      stopBuilding();
    } else if (!isLoading && !isDisabled) {
      send();
    }
  };

  return (
    <Button
      className={cn(
        buttonClasses,
        "h-[34px] w-[34px] rounded-full p-0 flex items-center justify-center border-0 transition-colors shadow-sm translate-y-[-2px]",
      )}
      onClick={handleClick}
      disabled={isDisabled}
      unstyled
      data-testid={isBuilding ? "button-stop" : "button-send"}
      aria-label={buttonLabel}
      title={buttonLabel}
    >
      <div className="flex h-fit w-fit items-center justify-center">
        {isBuilding ? (
          <Square className="h-3.5 w-3.5 fill-current text-white" aria-hidden />
        ) : (
          <IconSendOutline16 size={16} className="text-white" />
        )}
      </div>
    </Button>
  );
};

export default ButtonSendWrapper;
