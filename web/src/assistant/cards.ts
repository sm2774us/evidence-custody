import type { Advisory, Alert, ChainStatus, CustodyReport, Evidence, Ready, UploadInspect } from "@/lib/types";
import type { SigResult } from "@/lib/crypto";

export type Card =
  | { kind: "text"; text: string }
  | { kind: "help" }
  | { kind: "status"; ready: Ready; metrics: Record<string, number> }
  | { kind: "alerts"; status: string; items: Alert[] }
  | { kind: "chain"; result: ChainStatus }
  | { kind: "scan"; raised: number }
  | { kind: "evidence"; item: Evidence }
  | { kind: "custody"; view: CustodyReport; signature: SigResult }
  | { kind: "upload"; item: UploadInspect }
  | { kind: "advisory"; sessionId: string; advisory: Advisory }
  | { kind: "gaps"; device: string; missing: number[] }
  | { kind: "acked"; id: string }
  | { kind: "error"; message: string; status?: number; requestId?: string };
