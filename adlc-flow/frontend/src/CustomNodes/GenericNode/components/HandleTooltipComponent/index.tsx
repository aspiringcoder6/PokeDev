import { translateUi } from "@/i18n/ui";
import { useTranslation } from "react-i18next";
import { convertTestName } from "@/components/common/storeCardComponent/utils/convert-test-name";
import { Badge } from "@/components/ui/badge";
import { nodeColorsName } from "@/utils/styleUtils";

export default function HandleTooltipComponent({
  isInput,
  tooltipTitle,
  isConnecting,
  isCompatible,
  isSameNode,
  left,
}: {
  isInput: boolean;
  tooltipTitle: string;
  isConnecting: boolean;
  isCompatible: boolean;
  isSameNode: boolean;
  left: boolean;
}) {
  const { t } = useTranslation();
  const tooltips = tooltipTitle.split("\n");
  const plural = tooltips.length > 1 ? "s" : "";

  return (
    <div className="font-medium">
      {isSameNode ? (
        translateUi("Can't connect to the same node")
      ) : (
        <div className="flex items-center gap-1.5">
          {isConnecting ? (
            isCompatible ? (
              <span>
                <span className="font-semibold">{translateUi("Connect")}</span>{" "}
                {translateUi("to")}
              </span>
            ) : (
              <span>{t("node.incompatibleWith")}</span>
            )
          ) : (
            <span className="text-xs">
              {isInput
                ? translateUi("Input{{value0}} type{{value1}}", {
                    value0: plural,
                    value1: plural,
                  })
                : translateUi("Output{{value0}} type{{value1}}", {
                    value0: plural,
                    value1: plural,
                  })}
              :{" "}
            </span>
          )}
          {tooltips.map((word, index) => (
            <Badge
              className="h-6 rounded-md p-1"
              key={`${index}-${word.toLowerCase()}`}
              style={{
                backgroundColor: left
                  ? `hsl(var(--datatype-${nodeColorsName[word]}))`
                  : `hsl(var(--datatype-${nodeColorsName[word]}-foreground))`,
                color: left
                  ? `hsl(var(--datatype-${nodeColorsName[word]}-foreground))`
                  : `hsl(var(--datatype-${nodeColorsName[word]}))`,
              }}
              data-testid={`${isInput ? "input" : "output"}-tooltip-${convertTestName(word)}`}
            >
              {word}
            </Badge>
          ))}
          {isConnecting && <span>{isInput ? `input` : `output`}</span>}
        </div>
      )}
      {!isConnecting && (
        <div className="mt-2 flex flex-col gap-0.5 text-xs leading-6">
          <div>
            <b>{translateUi("Drag")}</b> {translateUi("to connect compatible")}{" "}
            {!isInput ? "inputs" : "outputs"}
          </div>
          <div>
            <b>{translateUi("Click")}</b> {translateUi("to filter compatible")}{" "}
            {!isInput ? "inputs" : "outputs"} {translateUi("and components")}
          </div>
        </div>
      )}
    </div>
  );
}
