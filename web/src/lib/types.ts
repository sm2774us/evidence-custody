export interface Ready { ready: boolean; audit_entries: number; audit_error: string | null }
export interface ChainStatus { ok: boolean; entries: number; head_hash: string; checkpoints_verified: number; error: string | null }
export interface Advisory {
  category: string; severity: "low" | "medium" | "high" | "critical"; summary: string; reasons: string[];
  recommended_actions: string[]; source: "rules" | "rules+llm"; model: string | null; prompt_sha256: string | null;
}
export interface Alert {
  alert_id: string; ts_ms: number; kind: string; severity: Advisory["severity"]; object_id: string | null;
  status: "open" | "acknowledged"; acked_by: string | null; acked_at_ms: number | null;
  detail: { advisory?: Advisory; object_id?: string };
}
export interface Hold { hold_id: string; case_ref: string; status: string }
export interface Evidence {
  evidence_id: string; agency_id: string; device_id: string; officer_id: string; case_id: string | null;
  sequence_no: number; sha256: string; size: number; media_type: string; version_id: string;
  retention_until_ms: number; captured_at_ms: number; received_at_ms: number; state: string; legal_holds: Hold[];
}
export interface AuditEntry {
  seq: number; ts_ms: number; actor: string; actor_role: string; action: string; object_type: string;
  object_id: string; object_version: string | null; source_ip: string | null; request_id: string | null;
  detail: Record<string, unknown>; prev_hash: string; entry_hash: string;
}
export interface UploadInspect {
  session_id: string; state: string; evidence_id: string | null; received_chunks: number[];
  missing_chunks: number[]; chunk_count: number; failure_reason: string | null; audit: AuditEntry[];
}
export interface CustodyReportBody {
  evidence_id: string; generated_at_ms: number; sha256_recorded: string; sha256_now: string; fixity_ok: boolean;
  receipt: Record<string, unknown>;
  derivatives: { derivative_id: string; kind: string; sha256: string; parent_sha256: string; created_by: string }[];
  legal_holds: Record<string, unknown>[]; custody_events: AuditEntry[];
  audit_chain: { ok: boolean; entries: number; head_hash: string; checkpoints_verified: number };
}
export interface CustodyReport { report: CustodyReportBody; signature: string; key_id: string }
export interface ServiceKey { key_id: string; public_key: string; alg: string }
