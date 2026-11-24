import { translateUi, useUiLocale } from "@/i18n/ui";
import { Textarea } from "../../../../../../../components/ui/textarea";

export default function ErrorOutput({ value }: { value: string }) {
  useUiLocale();
  return (
    <Textarea
      className={`h-full w-full text-destructive custom-scroll`}
      placeholder={translateUi("Empty")}
      value={value}
      readOnly
    />
  );
}
