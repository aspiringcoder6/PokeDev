import { ArrowLeft, ArrowRight, LoaderCircle, Play } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { deliveryApi, deliveryError } from "@/controllers/API/delivery";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";

export default function CanvasProjectBridge({
  flowId,
  projectId,
  name,
  disabled,
  save,
}: {
  flowId: string;
  projectId?: string;
  name: string;
  disabled: boolean;
  save: () => Promise<void>;
}) {
  const navigate = useCustomNavigate();
  const [open, setOpen] = useState(false),
    [title, setTitle] = useState(name),
    [requirement, setRequirement] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-4 py-2 text-xs">
        <button
          className="flex items-center gap-2 text-muted-foreground hover:text-foreground"
          onClick={() =>
            navigate(
              `/work?view=workflows${projectId ? `&project=${projectId}` : ""}`,
            )
          }
        >
          <ArrowLeft size={13} />
          Workspace / Workflow của project
        </button>
        <div className="flex items-center gap-3">
          <span className="hidden text-[10px] text-muted-foreground md:inline">
            {projectId
              ? "Workflow gắn với project đã chọn ở trên"
              : "Chọn project ở trên để dùng canvas cho một công việc"}
          </span>
          <Button
            size="sm"
            variant="outline"
            className="h-7 gap-2 text-[10px]"
            disabled={disabled || !projectId}
            onClick={() => {
              setOpen(true);
              setError("");
            }}
          >
            <Play size={12} />
            Tạo công việc từ canvas
          </Button>
        </div>
      </div>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!busy) setOpen(next);
        }}
      >
        <DialogContent>
          <DialogTitle>Dùng workflow cho project</DialogTitle>
          <DialogDescription>
            Lưu canvas và tạo một công việc riêng trong cùng project. Bạn duyệt
            kế hoạch trước khi bắt đầu thực hiện.
          </DialogDescription>
          <form
            className="space-y-4"
            onSubmit={async (event) => {
              event.preventDefault();
              if (busy || !projectId) return;
              setBusy(true);
              setError("");
              try {
                await save();
                const row = await deliveryApi.createFromCanvas(
                  flowId,
                  projectId,
                  title.trim(),
                  requirement.trim(),
                );
                navigate(`/work/${row.id}?project=${projectId}`);
              } catch (e) {
                setError(deliveryError(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="canvas-work-title">Tên công việc</Label>
              <Input
                id="canvas-work-title"
                required
                maxLength={120}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="canvas-work-requirement">
                Yêu cầu & tiêu chí
              </Label>
              <Textarea
                id="canvas-work-requirement"
                required
                minLength={20}
                maxLength={30000}
                rows={5}
                value={requirement}
                onChange={(event) => setRequirement(event.target.value)}
              />
            </div>
            {error && (
              <p role="alert" className="text-xs text-destructive">
                {error}
              </p>
            )}
            <Button disabled={busy} type="submit" className="w-full gap-2">
              {busy ? (
                <LoaderCircle size={14} className="animate-spin" />
              ) : (
                <ArrowRight size={14} />
              )}
              Tạo & xem công việc
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
