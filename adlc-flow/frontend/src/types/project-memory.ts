import type { VerificationScope } from "./verification";

export type MemoryScope = VerificationScope;
export interface MemoryBinding {
  workflow_run_id: string;
  project_id: string;
  base_commit: string;
  source_ref: string;
  source_task_id: string | null;
  source_attempt_id: string | null;
  source_session_id: string | null;
}
export interface MemoryQuery {
  query: string;
  top_k: number;
  idempotency_key: string;
}
export interface MemoryChunk {
  chunk_id: string;
  document_id: string;
  revision: string;
  source_uri: string;
  document_digest: string;
  text: string;
  text_digest: string;
  recorded_at: string;
  expires_at: string;
  source_commit: string | null;
}
export interface MemoryRead {
  content_digest: string;
  record: {
    schema_version: "0.1";
    profile_ref: "memory-profile:project-context/0.1.0";
    record_id: string;
    binding: MemoryBinding;
    query: string;
    top_k: number;
    tenant_id: string;
    dataset: string;
    backend_revision: string;
    retrieved_at: string;
    chunks: MemoryChunk[];
    authority: "ADVISORY_UNTRUSTED";
    verification_evidence: false;
    source_provenance_verified: false;
    models_used: false;
  };
}
export interface MemoryView {
  capabilities: {
    profile_ref: string;
    enabled: boolean;
    configured: boolean;
    live_certified: false;
    blockers: string[];
    synthesis_enabled: false;
    ingestion_enabled: false;
    deletion_enabled: false;
  };
  binding: MemoryBinding | null;
  tenant_id: string | null;
  dataset: string | null;
  records: MemoryRead[];
}
