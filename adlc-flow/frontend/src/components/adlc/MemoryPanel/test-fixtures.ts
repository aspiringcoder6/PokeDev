import type { MemoryRead, MemoryView } from "@/types/project-memory";

export function memoryFixture(): MemoryRead {
  return {
    content_digest: "sha256:" + "a".repeat(64),
    record: {
      schema_version: "0.1",
      profile_ref: "memory-profile:project-context/0.1.0",
      record_id: "memory-one",
      binding: {
        workflow_run_id: "run-one",
        project_id: "project-one",
        base_commit: "b".repeat(40),
        source_ref: "project-one/" + "b".repeat(40),
        source_task_id: "task-one",
        source_attempt_id: "attempt-one",
        source_session_id: "source-session",
      },
      query: "What did we decide about verification?",
      top_k: 5,
      tenant_id: "adlc-owner-offline-fixture",
      dataset: "adlc-project-offline-fixture",
      backend_revision: "offline-fixture:1",
      retrieved_at: "2026-10-13T04:00:00Z",
      authority: "ADVISORY_UNTRUSTED",
      verification_evidence: false,
      source_provenance_verified: false,
      models_used: false,
      chunks: [
        {
          chunk_id: "chunk-one",
          document_id: "verification-design-notes",
          revision: "r2",
          source_uri: "adlc://documents/verification-design-notes/r2",
          document_digest: "sha256:" + "c".repeat(64),
          text_digest: "sha256:" + "d".repeat(64),
          text: "Verify requires actual reproduction against a frozen standard. Retrieved memory is context only; the approved contract and retained evidence stay authoritative.",
          recorded_at: "2026-10-12T04:00:00Z",
          expires_at: "2099-10-13T04:00:00Z",
          source_commit: "b".repeat(40),
        },
      ],
    },
  };
}
export function memoryViewFixture(): MemoryView {
  const row = memoryFixture();
  return {
    capabilities: {
      profile_ref: row.record.profile_ref,
      enabled: true,
      configured: true,
      live_certified: false,
      blockers: [],
      synthesis_enabled: false,
      ingestion_enabled: false,
      deletion_enabled: false,
    },
    binding: row.record.binding,
    tenant_id: row.record.tenant_id,
    dataset: row.record.dataset,
    records: [row],
  };
}
