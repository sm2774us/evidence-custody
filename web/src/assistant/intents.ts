/** Deterministic intent router. No AI is required for the assistant to work; it maps
 *  plain-language requests onto existing, permission-checked API calls. */
export type Intent =
  | { kind: "help" } | { kind: "status" } | { kind: "verify" } | { kind: "scan" } | { kind: "checkpoint" }
  | { kind: "alerts"; status: "open" | "acknowledged" }
  | { kind: "evidence"; id: string } | { kind: "custody"; id: string }
  | { kind: "upload"; id: string } | { kind: "triage"; id: string }
  | { kind: "ack"; id: string } | { kind: "gaps"; device: string }
  | { kind: "unknown"; text: string };

const ID = /\b(ev|up|al|lh|dv)_[a-f0-9]{16,24}\b/i;
const idOf = (t: string, prefix: string): string | undefined =>
  new RegExp(`\\b${prefix}_[a-f0-9]{16,24}\\b`, "i").exec(t)?.[0].toLowerCase();

export function parseIntent(raw: string): Intent {
  const text = raw.trim();
  const t = text.toLowerCase().replace(/^\//, "");
  const ev = idOf(t, "ev"), up = idOf(t, "up"), al = idOf(t, "al");

  if (!t || /^(help|\?|commands|what can you do)/.test(t)) return { kind: "help" };
  if (al && /\b(ack|acknowledge|close|dismiss)\b/.test(t)) return { kind: "ack", id: al };
  if (up && /\b(triage|explain|why|advis|analy[sz]e)\b/.test(t)) return { kind: "triage", id: up };
  if (ev && /\b(custody|report|chain|history|fixity)\b/.test(t)) return { kind: "custody", id: ev };
  if (ev) return { kind: "evidence", id: ev };
  if (up) return { kind: "upload", id: up };
  const gaps = /\b(?:gaps?|missing|sequence)\s+(?:for\s+|of\s+)?([a-z0-9][\w.:-]{1,127})/i.exec(text);
  if (gaps && !ID.test(gaps[1]!)) return { kind: "gaps", device: gaps[1]! };
  if (/\b(verify|integrity|tamper|audit chain|check (the )?chain)\b/.test(t)) return { kind: "verify" };
  if (/\b(scan|anomal)/.test(t)) return { kind: "scan" };
  if (/\bcheckpoint\b/.test(t)) return { kind: "checkpoint" };
  if (/\b(alerts?|incidents?|issues?|problems?)\b/.test(t)) return { kind: "alerts", status: /\b(ack|acknowledged|closed|resolved)\b/.test(t) ? "acknowledged" : "open" };
  if (/\b(status|health|ready|how are we|overview|summary)\b/.test(t)) return { kind: "status" };
  return { kind: "unknown", text };
}

export const SUGGESTIONS = [
  "status", "open alerts", "verify audit chain", "scan for anomalies",
  "evidence ev_…", "custody report ev_…", "upload up_…", "why up_…", "gaps cam-0001",
];
