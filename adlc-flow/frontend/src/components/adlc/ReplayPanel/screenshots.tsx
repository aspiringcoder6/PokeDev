import { translateUi, useUiLocale } from "@/i18n/ui";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  attachReplayScreenshot,
  listReplayScreenshots,
  loadReplayScreenshot,
  testExtensionCapabilities,
} from "@/controllers/API/test-extensions";
import type { ReplayRead } from "@/types/replay";
import type { ScreenshotRead } from "@/types/test-extensions";

export function supportedScreenshot(image: ScreenshotRead, row: ReplayRead) {
  return (
    image?.schema_version === "0.1" &&
    image.profile_ref === "evidence-profile:supplementary-png/0.1.0" &&
    image.authority === "SUPPLEMENTARY_UNTRUSTED" &&
    image.affects_verdict === false &&
    image.capture_provenance_verified === false &&
    image.workflow_run_id === row.plan.workflow_run_id &&
    image.plan_id === row.plan.plan_id &&
    image.plan_digest === row.plan_digest &&
    image.execution_id === row.execution_id &&
    image.candidate_digest === row.plan.candidate.content_digest &&
    image.case_evidence_digest === row.evidence_digest &&
    row.plan.cases.some((c) => c.case_id === image.case_id) &&
    typeof image.caption === "string" &&
    image.caption.length > 0 &&
    image.caption.length <= 240 &&
    typeof image.attachment_id === "string" &&
    /^[A-Za-z0-9-]{1,64}$/.test(image.attachment_id) &&
    typeof image.uploaded_by === "string" &&
    image.uploaded_by.length > 0 &&
    image.uploaded_by.length <= 255 &&
    /^sha256:[0-9a-f]{64}$/.test(image.content_digest) &&
    image.media_type === "image/png" &&
    Number.isInteger(image.byte_size) &&
    image.byte_size > 0 &&
    image.byte_size <= 262144 &&
    Number.isInteger(image.width) &&
    image.width > 0 &&
    image.width <= 4096 &&
    Number.isInteger(image.height) &&
    image.height > 0 &&
    image.height <= 4096 &&
    image.width * image.height <= 4_000_000 &&
    typeof image.uploaded_at === "string" &&
    Number.isFinite(Date.parse(image.uploaded_at))
  );
}
export default function ReplayScreenshots({
  row,
  identity,
  human,
}: {
  row: ReplayRead;
  identity: string;
  human: boolean;
}) {
  useUiLocale();
  const current = useRef(identity);
  current.current = identity;
  const mounted = useRef(true);
  const [open, setOpen] = useState(false),
    [loaded, setLoaded] = useState<string>(),
    [rows, setRows] = useState<ScreenshotRead[]>([]);
  const [enabled, setEnabled] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string>();
  const [urls, setUrls] = useState<Record<string, string>>({});
  const ownedUrls = useRef(new Set<string>());
  const [file, setFile] = useState<File>(),
    [caption, setCaption] = useState(""),
    [caseId, setCaseId] = useState(row.plan.cases[0]?.case_id ?? "");
  const key = useRef<string | undefined>(undefined);
  useEffect(() => {
    mounted.current = true;
    setOpen(false);
    setRows([]);
    setUrls({});
    setLoaded(undefined);
    setEnabled(false);
    setFile(undefined);
    setCaption("");
    setBusy(false);
    setError(undefined);
    key.current = undefined;
    return () => {
      mounted.current = false;
      for (const url of ownedUrls.current) URL.revokeObjectURL(url);
      ownedUrls.current.clear();
    };
  }, [identity]);
  async function load() {
    const captured = identity;
    setOpen(true);
    setBusy(true);
    setError(undefined);
    try {
      const [images, caps] = await Promise.all([
        listReplayScreenshots(row),
        testExtensionCapabilities(),
      ]);
      if (!mounted.current || current.current !== captured) return;
      setRows(images);
      setLoaded(captured);
      setEnabled(
        caps.schema_version === "0.1" &&
          caps.profile_ref === "test-extension-profile:proposals/0.1.0" &&
          caps.enabled === true &&
          caps.human_actions_configured === true &&
          caps.screenshot_capture_ready === false,
      );
    } catch {
      if (mounted.current && current.current === captured) {
        setRows([]);
        setEnabled(false);
        setError(
          translateUi(
            "Screenshot archive unavailable. The official report remains unchanged.",
          ),
        );
      }
    } finally {
      if (mounted.current && current.current === captured) setBusy(false);
    }
  }
  async function preview(image: ScreenshotRead) {
    const captured = identity;
    setBusy(true);
    setError(undefined);
    try {
      const blob = await loadReplayScreenshot(row, image);
      if (!mounted.current || current.current !== captured) return;
      const url = URL.createObjectURL(blob);
      ownedUrls.current.add(url);
      setUrls((old) => ({ ...old, [image.attachment_id]: url }));
    } catch {
      if (mounted.current && current.current === captured)
        setError(
          translateUi(
            "Image checksum or ownership could not be confirmed. No preview was loaded.",
          ),
        );
    } finally {
      if (mounted.current && current.current === captured) setBusy(false);
    }
  }
  return (
    <section
      aria-label={translateUi("Supplementary screenshots")}
      className="space-y-2 rounded border border-dashed p-3"
    >
      <h4 className="text-sm font-medium">
        {translateUi("Screenshots · supplementary references")}
      </h4>
      <p className="text-xs text-muted-foreground">
        {translateUi(
          "Owner-attached PNGs, not trusted browser captures or verification evidence. They cannot change PASS/FAIL. Automated screenshot capture is not available in this fixture profile.",
        )}
      </p>
      <Button
        variant="outline"
        size="sm"
        disabled={busy}
        onClick={() => void load()}
      >
        {translateUi("Load screenshot archive")}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {open && loaded === identity && (
        <>
          {!rows.length && (
            <p className="text-xs">
              {translateUi(
                "No screenshot references retained for this execution.",
              )}
            </p>
          )}
          <div className="grid gap-3 md:grid-cols-2">
            {rows.map((image, i) =>
              supportedScreenshot(image, row) ? (
                <figure
                  key={image.attachment_id}
                  className="min-w-0 space-y-2 rounded border p-2"
                >
                  {urls[image.attachment_id] ? (
                    <img
                      src={urls[image.attachment_id]}
                      alt={image.caption}
                      className="max-h-64 max-w-full object-contain"
                    />
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => void preview(image)}
                    >
                      {translateUi("Preview reference")} {i + 1}
                    </Button>
                  )}
                  <figcaption className="break-words text-xs">
                    {image.caption} {translateUi("· case")} {image.case_id}
                  </figcaption>
                  <p className="break-all text-xs text-muted-foreground">
                    {image.width}×{image.height} · {image.byte_size}{" "}
                    {translateUi("bytes · uploaded by")}
                    {image.uploaded_by}
                    <br />
                    {image.content_digest}
                    <br />
                    {translateUi(
                      "Capture provenance: unverified · no verdict authority",
                    )}
                  </p>
                </figure>
              ) : (
                <p key={`unsupported-${i}`} className="text-xs">
                  {translateUi(
                    "Unsupported screenshot metadata · no image loaded.",
                  )}
                </p>
              ),
            )}
          </div>
          {human && enabled && rows.length < 4 && (
            <form
              className="space-y-2 border-t pt-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (!file || !caption.trim() || busy) return;
                const captured = identity;
                setBusy(true);
                setError(undefined);
                key.current ??= crypto.randomUUID();
                void attachReplayScreenshot(
                  row,
                  file,
                  caption,
                  caseId,
                  key.current,
                )
                  .then(async () => {
                    if (!mounted.current || current.current !== captured)
                      return;
                    setFile(undefined);
                    setCaption("");
                    key.current = undefined;
                    await load();
                  })
                  .catch(() => {
                    if (mounted.current && current.current === captured)
                      setError(
                        translateUi(
                          "Reference could not be saved. Use a single PNG ≤256 KiB (≤4096 per dimension, ≤4 million pixels). Refresh before retrying an uncertain save.",
                        ),
                      );
                  })
                  .finally(() => {
                    if (mounted.current && current.current === captured)
                      setBusy(false);
                  });
              }}
            >
              <label className="block text-xs">
                {translateUi("Reference PNG (not evidence)")}
                <input
                  className="mt-1 block w-full"
                  type="file"
                  accept="image/png"
                  disabled={busy}
                  onChange={(e) => {
                    setFile(e.target.files?.[0]);
                    key.current = undefined;
                  }}
                />
              </label>
              <label className="block text-xs">
                {translateUi("Caption")}
                <input
                  className="mt-1 w-full rounded border bg-background p-2"
                  value={caption}
                  maxLength={240}
                  disabled={busy}
                  onChange={(e) => {
                    setCaption(e.target.value);
                    key.current = undefined;
                  }}
                />
              </label>
              <label className="block text-xs">
                {translateUi("Case")}
                <select
                  className="mt-1 w-full rounded border bg-background p-2"
                  value={caseId}
                  disabled={busy}
                  onChange={(e) => {
                    setCaseId(e.target.value);
                    key.current = undefined;
                  }}
                >
                  {row.plan.cases.map((c) => (
                    <option key={c.case_id}>{c.case_id}</option>
                  ))}
                </select>
              </label>
              <Button
                size="sm"
                type="submit"
                disabled={busy || !file || !caption.trim()}
              >
                {translateUi("Attach supplementary PNG")}
              </Button>
            </form>
          )}
        </>
      )}
    </section>
  );
}
