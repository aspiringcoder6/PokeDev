import { translateUi, useUiLocale } from "@/i18n/ui";
import { useParams, useSearchParams } from "react-router-dom";
import ContractExecutionPanel from "@/components/adlc/ContractExecutionPanel";
import ContractPanel from "@/components/adlc/ContractPanel";
import { useTranslation } from "react-i18next";
import "@/i18n";
import MemoryPanel from "@/components/adlc/MemoryPanel";
import ReplayPanel from "@/components/adlc/ReplayPanel";
import VerificationPanel from "@/components/adlc/VerificationPanel";

// Same renderer and owner-authorized API as Run Detail, not a Harness copy.
export default function ContractHarnessPage() {
  useUiLocale();
  const { sessionId } = useParams();
  const [params] = useSearchParams();
  if (!sessionId || !/^[A-Za-z0-9._-]{1,255}$/.test(sessionId))
    return <p>{translateUi("Invalid session identity.")}</p>;
  if (params.get("view") === "memory")
    return (
      <main className="h-full overflow-auto bg-background p-3">
        <MemoryPanel key={sessionId} scope={{ sessionId }} readOnly />
      </main>
    );
  if (params.get("view") === "verification")
    return (
      <main className="h-full space-y-4 overflow-auto bg-background p-3">
        <VerificationPanel key={sessionId} scope={{ sessionId }} readOnly />
        <ReplayPanel
          key={`replay-${sessionId}`}
          scope={{ sessionId }}
          readOnly
        />
        <MemoryPanel
          key={`verify-memory-${sessionId}`}
          scope={{ sessionId }}
          readOnly
        />
      </main>
    );
  return (
    <main className="h-full space-y-4 overflow-auto bg-background p-3">
      <ContractPanel key={sessionId} scope={{ sessionId }} readOnly />
      <ContractExecutionPanel
        key={`execution-${sessionId}`}
        scope={{ sessionId }}
      />
      <VerificationPanel
        key={`verify-${sessionId}`}
        scope={{ sessionId }}
        readOnly
      />
      <ReplayPanel key={`replay-${sessionId}`} scope={{ sessionId }} readOnly />
      <MemoryPanel key={`memory-${sessionId}`} scope={{ sessionId }} readOnly />
    </main>
  );
}
