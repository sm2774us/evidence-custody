import { useSession } from "@/store/session";
import type {
  Advisory, Alert, AuditEntry, ChainStatus, CustodyReport, Evidence, Ready, ServiceKey, UploadInspect,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly extra: Record<string, unknown>;
  constructor(status: number, code: string, message: string, requestId?: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.extra = extra;
  }
  /** Network failure or 5xx: worth retrying. 4xx are deterministic and are not. */
  get retryable(): boolean { return this.status === 0 || this.status >= 500; }
}

interface Opts {
  method?: string;
  body?: BodyInit | null;
  json?: unknown;
  headers?: Record<string, string>;
  query?: Record<string, string | number | undefined>;
  timeoutMs?: number;
  auth?: boolean;
}

async function send(path: string, o: Opts = {}): Promise<Response> {
  const url = new URL(path, window.location.origin);
  for (const [k, v] of Object.entries(o.query ?? {})) if (v !== undefined) url.searchParams.set(k, String(v));
  const headers: Record<string, string> = { ...o.headers };
  const token = useSession.getState().token;
  if (o.auth !== false && token) headers.authorization = `Bearer ${token}`;
  let body = o.body ?? null;
  if (o.json !== undefined) { body = JSON.stringify(o.json); headers["content-type"] = "application/json"; }

  const ctl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, o.timeoutMs ?? 15_000);
  let res: Response;
  try {
    res = await fetch(url, { method: o.method ?? "GET", headers, body, signal: ctl.signal, cache: "no-store", credentials: "omit" });
  } catch {
    throw new ApiError(0, timedOut ? "timeout" : "network",
      timedOut ? "The service did not respond in time." : "Cannot reach the service. Check your connection.");
  } finally {
    clearTimeout(timer);
  }
  if (res.ok) return res;

  const requestId = res.headers.get("x-request-id") ?? undefined;
  let payload: Record<string, unknown> = {};
  try { payload = (await res.json()) as Record<string, unknown>; } catch { /* non-JSON error body */ }
  const { error, message, detail, ...extra } = payload;
  if (res.status === 401 && o.auth !== false) useSession.getState().signOut("Your session is no longer valid. Sign in again.");
  const msg = typeof message === "string" ? message
    : Array.isArray(detail) ? "The request was malformed." : res.statusText || "Request failed";
  throw new ApiError(res.status, typeof error === "string" ? error : `http_${res.status}`, msg, requestId, extra);
}

const json = async <T>(path: string, o?: Opts): Promise<T> => (await send(path, o)).json() as Promise<T>;
const post = <T>(path: string, o: Opts = {}) => json<T>(path, { ...o, method: "POST" });
const enc = encodeURIComponent;

export const api = {
  /** /readyz answers 503 with JSON when the audit chain is broken: surface it, never hide it. */
  ready: (): Promise<Ready> =>
    json<Ready>("/readyz", { auth: false, timeoutMs: 6000 }).catch((e: unknown) => {
      if (e instanceof ApiError && e.status === 503) {
        return { ready: false, audit_entries: Number(e.extra.audit_entries ?? 0), audit_error: String(e.extra.audit_error ?? "audit chain failed verification") };
      }
      throw e;
    }),
  metricsText: async () => (await send("/metrics", { auth: false, timeoutMs: 6000 })).text(),
  keys: () => json<ServiceKey>("/v1/keys", { auth: false }),

  alerts: (status: "open" | "acknowledged") => json<{ alerts: Alert[] }>("/v1/alerts", { query: { status } }).then((r) => r.alerts),
  ackAlert: (id: string) => post<{ alert_id: string; status: string }>(`/v1/alerts/${enc(id)}/ack`),

  audit: (after = 0, limit = 200) => json<{ entries: AuditEntry[] }>("/v1/audit", { query: { after, limit } }).then((r) => r.entries),
  auditVerify: () => post<ChainStatus>("/v1/audit/verify"),
  auditScan: () => post<{ alerts: unknown[] }>("/v1/audit/scan"),
  auditCheckpoint: () => post<Record<string, unknown>>("/v1/audit/checkpoint"),

  evidence: (id: string) => json<Evidence>(`/v1/evidence/${enc(id)}`),
  custody: (id: string) => json<CustodyReport>(`/v1/evidence/${enc(id)}/custody`, { timeoutMs: 60_000 }),
  content: async (id: string, reason: string) => {
    const res = await send(`/v1/evidence/${enc(id)}/content`, { headers: { "x-access-reason": reason }, timeoutMs: 10 * 60_000 });
    return { blob: await res.blob(), headerSha256: res.headers.get("x-content-sha256") ?? "" };
  },
  derivative: (id: string, kind: string, file: File, params: Record<string, unknown>) =>
    post<{ derivative_id: string; sha256: string; parent_sha256: string; kind: string }>(`/v1/evidence/${enc(id)}/derivatives`, {
      query: { kind }, body: file, timeoutMs: 5 * 60_000,
      headers: { "content-type": file.type || "application/octet-stream", "x-params": JSON.stringify(params) },
    }),
  requestHold: (id: string, case_ref: string, reason: string) =>
    post<{ hold_id: string; status: string }>(`/v1/evidence/${enc(id)}/holds`, { json: { case_ref, reason } }),
  approveHold: (id: string) => post<{ hold_id: string; status: string }>(`/v1/holds/${enc(id)}/approve`),
  releaseHold: (id: string, reason: string) => post<{ hold_id: string; status: string }>(`/v1/holds/${enc(id)}/release`, { query: { reason } }),

  inspectUpload: (id: string) => json<UploadInspect>(`/v1/uploads/${enc(id)}/inspect`),
  triage: (id: string) => post<Advisory>(`/v1/uploads/${enc(id)}/triage`),
  disposition: (id: string, decision: "retry_authorized" | "retain_for_investigation", note: string) =>
    post<{ session_id: string; decision: string }>(`/v1/quarantine/${enc(id)}/disposition`, { json: { decision, note } }),

  registerDevice: (b: { device_id: string; public_key: string; officer_id: string; agency_id: string }) =>
    post<{ device_id: string; status: string }>("/v1/devices", { json: b }),
  activateDevice: (id: string) => post<{ device_id: string; status: string }>(`/v1/devices/${enc(id)}/activate`),
  revokeDevice: (id: string, reason: string) => post<{ device_id: string; status: string }>(`/v1/devices/${enc(id)}/revoke`, { query: { reason } }),
  gaps: (id: string) => json<{ device_id: string; missing: number[] }>(`/v1/devices/${enc(id)}/sequence-gaps`).then((r) => r.missing),
};
