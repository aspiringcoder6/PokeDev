import { translateUi, useUiLocale } from "@/i18n/ui";
import { useEffect, useRef, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  type AdlcBlueprintGenerationResult,
  generateAdlcBlueprint,
} from "@/controllers/API/adlc";
import { getAdlcPlanningError } from "@/utils/adlc-blueprint";
import { useTranslation } from "react-i18next";
import "@/i18n";

type BlueprintRequestDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flowId: string;
  /** True when the flow already carries blueprint stages (modify mode). */
  hasStages: boolean;
  onGenerated: (result: AdlcBlueprintGenerationResult) => void;
  /**
   * Optional pre-filled requirement text. When provided, the textarea is
   * populated with this value as soon as the dialog opens. The user can
   * still edit, clear, or replace the text before submitting. Useful for
   * demos where the same example is shown repeatedly.
   */
  defaultRequirement?: string;
  /**
   * Optional pre-filled extra instructions. Same semantics as
   * ``defaultRequirement`` but for the secondary textarea.
   */
  defaultInstructions?: string;
};

export default function BlueprintRequestDialog({
  open,
  onOpenChange,
  flowId,
  hasStages,
  onGenerated,
  defaultRequirement,
  defaultInstructions,
}: BlueprintRequestDialogProps) {
  useUiLocale();
  const [requirement, setRequirement] = useState("");
  const [instructions, setInstructions] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestToken = useRef(0);

  // Pre-fill the textareas with the provided defaults whenever the dialog
  // opens. This lets demos show a ready-to-submit example without forcing
  // the user to type it. The user can still edit, clear, or replace the
  // text before submitting.
  useEffect(() => {
    if (!open) return;
    if (defaultRequirement !== undefined) {
      setRequirement(defaultRequirement);
    }
    if (defaultInstructions !== undefined) {
      setInstructions(defaultInstructions);
    }
  }, [open, defaultRequirement, defaultInstructions]);

  // Invalidate any in-flight generation when the dialog closes or the
  // component unmounts, so a late response is never applied unexpectedly.
  useEffect(() => {
    if (open) return;
    requestToken.current += 1;
    setIsGenerating(false);
  }, [open]);

  useEffect(
    () => () => {
      requestToken.current += 1;
    },
    [],
  );

  const close = (next: boolean) => {
    if (isGenerating && !next) return;
    onOpenChange(next);
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (isGenerating || !requirement.trim()) {
      if (!requirement.trim()) {
        setError(
          translateUi(
            "Describe what the workflow should do before sending the request.",
          ),
        );
      }
      return;
    }
    const token = requestToken.current + 1;
    requestToken.current = token;
    setIsGenerating(true);
    setError(null);
    try {
      const result = await generateAdlcBlueprint(
        flowId,
        requirement.trim(),
        instructions.trim() || undefined,
      );
      if (requestToken.current !== token) return;
      onGenerated(result);
      setRequirement("");
      setInstructions("");
      onOpenChange(false);
    } catch (requestError) {
      if (requestToken.current !== token) return;
      const { message } = getAdlcPlanningError(requestError);
      setError(message);
    } finally {
      if (requestToken.current === token) {
        setIsGenerating(false);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent
        className="max-h-[88vh] max-w-2xl gap-0 overflow-hidden p-0"
        hideCloseButton={isGenerating}
        onEscapeKeyDown={(event) => {
          if (isGenerating) event.preventDefault();
        }}
        onInteractOutside={(event) => {
          if (isGenerating) event.preventDefault();
        }}
        data-testid="adlc-blueprint-request-dialog"
      >
        <DialogHeader className="border-b px-6 py-5">
          <DialogTitle>
            {hasStages
              ? translateUi("Request a blueprint change")
              : translateUi("Describe your workflow")}
          </DialogTitle>
          <DialogDescription>
            {hasStages
              ? translateUi(
                  "Send a change request and the DeepSeek Harness agent returns an updated blueprint. You can still adjust stages, bindings and constraints by hand afterwards.",
                )
              : translateUi(
                  "Send your requirement to the DeepSeek Harness agent and it returns a ready-to-edit blueprint with stages and dependencies. Close this dialog to build the blueprint manually instead.",
                )}
          </DialogDescription>
        </DialogHeader>
        <form className="flex min-h-0 flex-1 flex-col" onSubmit={submit}>
          <div className="flex flex-col gap-5 overflow-y-auto px-6 py-5">
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="adlc-blueprint-requirement"
              >
                {hasStages
                  ? translateUi("Requested change")
                  : translateUi("Workflow requirement")}
              </label>
              <Textarea
                id="adlc-blueprint-requirement"
                className="min-h-32"
                autoFocus
                value={requirement}
                onChange={(event) => setRequirement(event.target.value)}
                placeholder={
                  hasStages
                    ? translateUi(
                        "e.g. Add a testing stage after implementation and require approval before release.",
                      )
                    : translateUi(
                        "e.g. Build a todo list app: capture the requirement, implement the frontend, run functional tests, then require human approval.",
                      )
                }
                disabled={isGenerating}
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="adlc-blueprint-instructions"
              >
                {translateUi("Extra instructions")}{" "}
                <span className="text-muted-foreground">(optional)</span>
              </label>
              <Textarea
                id="adlc-blueprint-instructions"
                className="min-h-16"
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
                placeholder={translateUi(
                  "Constraints the planner should honor, e.g. 'Keep a single approval gate at the end.'",
                )}
                disabled={isGenerating}
              />
            </div>
            {error && (
              <p className="rounded-md bg-error-background px-3 py-2 text-sm text-error-foreground">
                {error}
              </p>
            )}
            {isGenerating && (
              <div className="flex items-center gap-2 rounded-md border px-3 py-3 text-sm text-muted-foreground">
                <ForwardedIconComponent
                  name="Loader2"
                  className="h-4 w-4 animate-spin text-primary"
                />
                {translateUi(
                  "Sending the request to the DeepSeek Harness server. The agent turn can take a few minutes — the blueprint is applied as soon as it replies.",
                )}
              </div>
            )}
          </div>
          <DialogFooter className="border-t px-6 py-4">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={isGenerating}
            >
              {translateUi("Close and build manually")}
            </Button>
            <Button
              type="submit"
              loading={isGenerating}
              disabled={!requirement.trim()}
              data-testid="adlc-blueprint-request-submit"
            >
              {isGenerating
                ? translateUi("Generating blueprint…")
                : hasStages
                  ? translateUi("Send change request")
                  : translateUi("Generate blueprint")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
