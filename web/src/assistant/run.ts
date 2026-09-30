import { ApiError, api } from "@/lib/api";
import { can, type Role } from "@/lib/auth";
import { verifySignedObject } from "@/lib/crypto";
import { parseMetrics } from "@/lib/metrics";
import type { Card } from "./cards";
import type { Intent } from "./intents";

const need = (role: Role | undefined, perm: string, what: string): Card | null =>
  can(role, perm) ? null : { kind: "error", status: 403, message: `Your role (${role ?? "unknown"}) cannot ${what}. Ask a user with the right role.` };

export async function execute(intent: Intent, role: Role | undefined): Promise<Card> {
  try {
    switch (intent.kind) {
      case "help": return { kind: "help" };
      case "status": {
        const [ready, m] = await Promise.all([api.ready(), api.metricsText().then(parseMetrics).catch(() => ({}))]);
        return { kind: "status", ready, metrics: m };
      }
      case "alerts":
        return need(role, "alerts:read", "read alerts") ?? { kind: "alerts", status: intent.status, items: await api.alerts(intent.status) };
      case "verify":
        return need(role, "audit:verify", "verify the audit chain") ?? { kind: "chain", result: await api.auditVerify() };
      case "scan":
        return need(role, "audit:scan", "run an anomaly scan") ?? { kind: "scan", raised: (await api.auditScan()).alerts.length };
      case "checkpoint": {
        const d = need(role, "audit:checkpoint", "sign an audit checkpoint");
        if (d) return d;
        await api.auditCheckpoint();
        return { kind: "text", text: "Signed audit checkpoint recorded. Export it to your independent anchor store." };
      }
      case "evidence":
        return need(role, "evidence:read", "read evidence metadata") ?? { kind: "evidence", item: await api.evidence(intent.id) };
      case "custody": {
        const d = need(role, "custody:report", "generate custody reports");
        if (d) return d;
        const [view, key] = await Promise.all([api.custody(intent.id), api.keys()]);
        return { kind: "custody", view, signature: await verifySignedObject(key.public_key, view.signature, view.report) };
      }
      case "upload":
        return need(role, "upload:inspect", "inspect uploads") ?? { kind: "upload", item: await api.inspectUpload(intent.id) };
      case "triage":
        return need(role, "triage:run", "run triage") ?? { kind: "advisory", sessionId: intent.id, advisory: await api.triage(intent.id) };
      case "ack": {
        const d = need(role, "alerts:ack", "acknowledge alerts");
        if (d) return d;
        await api.ackAlert(intent.id);
        return { kind: "acked", id: intent.id };
      }
      case "gaps":
        return need(role, "evidence:read", "read sequence gaps") ?? { kind: "gaps", device: intent.device, missing: await api.gaps(intent.device) };
      case "unknown":
        return { kind: "text", text: `I did not understand “${intent.text}”. Try one of the suggestions below, or type help.` };
    }
  } catch (e) {
    if (e instanceof ApiError) return { kind: "error", message: e.message, status: e.status, requestId: e.requestId };
    return { kind: "error", message: e instanceof Error ? e.message : "Unexpected error" };
  }
}
