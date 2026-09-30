import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2, ShieldAlert, ShieldCheck, XCircle } from "lucide-react";
import { toast } from "sonner";
import type { Card } from "@/assistant/cards";
import { SUGGESTIONS } from "@/assistant/intents";
import { api } from "@/lib/api";
import { fmtBytes, fmtTime, relTime } from "@/lib/utils";
import { Badge, SeverityBadge, StateBadge } from "@/components/ui/badge";
import { HashChip, ConfirmButton } from "@/components/ui/misc";
import { Button } from "@/components/ui/button";

const Row = ({ k, children }: { k: string; children: React.ReactNode }) => (
  <div className="flex items-start justify-between gap-4 py-1 text-sm"><span className="text-muted-foreground">{k}</span><span className="min-w-0 text-right">{children}</span></div>
);

function AckButton({ id }: { id: string }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.ackAlert(id),
    onSuccess: () => { toast.success(`Acknowledged ${id}`); void qc.invalidateQueries({ queryKey: ["alerts"] }); },
    onError: (e) => toast.error(e.message),
  });
  return <ConfirmButton label="Acknowledge" confirmLabel="Confirm ack" onConfirm={() => m.mutate()} loading={m.isPending} />;
}

export function CardView({ card, onSend }: { card: Card; onSend?: (text: string) => void }) {
  switch (card.kind) {
    case "text": return <p className="text-sm leading-relaxed">{card.text}</p>;
    case "help": return (
      <div className="space-y-2 text-sm">
        <p>I turn plain requests into permission-checked calls to the custody API. Everything I show comes from the service; nothing is guessed.</p>
        <ul className="grid gap-1 sm:grid-cols-2">
          {SUGGESTIONS.map((s) => <li key={s}><button type="button" className="w-full rounded-md border px-2 py-1 text-left font-mono text-xs hover:bg-muted" onClick={() => onSend?.(s)}>{s}</button></li>)}
        </ul>
        <p className="text-xs text-muted-foreground">Changes (acknowledging an alert) always need a second confirming click.</p>
      </div>
    );
    case "status": {
      const m = card.metrics;
      return (
        <div>
          <div className="mb-2 flex items-center gap-2">
            {card.ready.ready ? <ShieldCheck className="size-5 text-success" /> : <ShieldAlert className="size-5 text-danger" />}
            <b>{card.ready.ready ? "Operational" : "Audit integrity failure"}</b>
          </div>
          <Row k="Audit entries">{card.ready.audit_entries}</Row>
          {card.ready.audit_error ? <Row k="Audit error"><span className="text-danger">{card.ready.audit_error}</span></Row> : null}
          <Row k="Evidence stored">{m.custody_evidence_stored_total ?? 0}</Row>
          <Row k="Hash mismatches">{m.custody_hash_mismatch_total ?? 0}</Row>
          <Row k="Open alerts">{m.custody_open_alerts ?? 0}</Row>
          <Row k="Quarantined uploads">{m.custody_quarantined_sessions ?? 0}</Row>
          <Row k="Oldest open upload">{Math.round(m.custody_oldest_open_upload_age_seconds ?? 0)}s</Row>
        </div>
      );
    }
    case "alerts": return card.items.length === 0 ? <p className="text-sm">No {card.status} alerts. 🎉</p> : (
      <ul className="space-y-2">
        {card.items.slice(0, 8).map((a) => (
          <li key={a.alert_id} className="rounded-md border p-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex items-center gap-2"><SeverityBadge severity={a.severity} /><b className="text-sm">{a.kind}</b></span>
              <span className="text-xs text-muted-foreground">{relTime(a.ts_ms)}</span>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">{a.detail.advisory?.summary}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <HashChip value={a.object_id} />
              {a.status === "open" ? <AckButton id={a.alert_id} /> : <Badge tone="ok">acknowledged by {a.acked_by}</Badge>}
            </div>
          </li>
        ))}
        {card.items.length > 8 ? <li className="text-xs text-muted-foreground">+{card.items.length - 8} more on the <Link to="/alerts" className="underline">Alerts page</Link>.</li> : null}
      </ul>
    );
    case "chain": return (
      <div>
        <div className="mb-2 flex items-center gap-2">{card.result.ok ? <CheckCircle2 className="size-5 text-success" /> : <XCircle className="size-5 text-danger" />}<b>{card.result.ok ? "Audit chain intact" : "Audit chain BROKEN"}</b></div>
        <Row k="Entries checked">{card.result.entries}</Row>
        <Row k="Signed checkpoints verified">{card.result.checkpoints_verified}</Row>
        <Row k="Head hash"><HashChip value={card.result.head_hash} /></Row>
        {card.result.error ? <Row k="Error"><span className="text-danger">{card.result.error}</span></Row> : null}
      </div>
    );
    case "scan": return <p className="text-sm">Anomaly scan finished: <b>{card.raised}</b> pattern{card.raised === 1 ? "" : "s"} flagged{card.raised ? " (see open alerts)." : "."}</p>;
    case "evidence": {
      const e = card.item;
      return (
        <div>
          <div className="mb-1 flex items-center justify-between"><HashChip value={e.evidence_id} full /><StateBadge state={e.state} /></div>
          <Row k="Size / type">{fmtBytes(e.size)} · {e.media_type}</Row>
          <Row k="SHA-256"><HashChip value={e.sha256} /></Row>
          <Row k="Device / officer">{e.device_id} · {e.officer_id}</Row>
          <Row k="Case">{e.case_id ?? "—"}</Row>
          <Row k="Retained until">{fmtTime(e.retention_until_ms)}</Row>
          <Row k="Legal holds">{e.legal_holds.length ? e.legal_holds.map((h) => h.case_ref).join(", ") : "none"}</Row>
          <div className="mt-2 flex gap-2"><Button size="sm" variant="outline" asChild><Link to="/evidence/$id" params={{ id: e.evidence_id }}>Open evidence</Link></Button>
            <Button size="sm" variant="ghost" onClick={() => onSend?.(`custody report ${e.evidence_id}`)}>Custody report</Button></div>
        </div>
      );
    }
    case "custody": {
      const r = card.view.report;
      return (
        <div>
          <div className="mb-2 flex flex-wrap gap-2">
            <Badge tone={r.fixity_ok ? "ok" : "danger"}>{r.fixity_ok ? "fixity OK" : "FIXITY FAILED"}</Badge>
            <Badge tone={r.audit_chain.ok ? "ok" : "danger"}>{r.audit_chain.ok ? "audit chain OK" : "AUDIT CHAIN BROKEN"}</Badge>
            <Badge tone={card.signature === "valid" ? "ok" : card.signature === "invalid" ? "danger" : "warn"}>
              signature {card.signature === "unsupported" ? "unchecked (browser)" : card.signature}
            </Badge>
          </div>
          <Row k="Custody events">{r.custody_events.length}</Row>
          <Row k="Derivatives">{r.derivatives.length}</Row>
          <Row k="Recorded hash"><HashChip value={r.sha256_recorded} /></Row>
          <Row k="Hash now"><HashChip value={r.sha256_now} /></Row>
          <Button size="sm" variant="outline" className="mt-2" asChild><Link to="/evidence/$id" params={{ id: r.evidence_id }} search={{ tab: "custody" }}>Full report</Link></Button>
        </div>
      );
    }
    case "upload": {
      const u = card.item;
      return (
        <div>
          <div className="mb-1 flex items-center justify-between"><HashChip value={u.session_id} full /><StateBadge state={u.state} /></div>
          <Row k="Chunks received">{u.received_chunks.length} / {u.chunk_count}</Row>
          {u.failure_reason ? <Row k="Failure"><span className="text-danger">{u.failure_reason}</span></Row> : null}
          {u.evidence_id ? <Row k="Evidence"><HashChip value={u.evidence_id} /></Row> : null}
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="outline" asChild><Link to="/uploads/$id" params={{ id: u.session_id }}>Open upload</Link></Button>
            {u.state === "quarantined" ? <Button size="sm" variant="ghost" onClick={() => onSend?.(`why ${u.session_id}`)}>Explain quarantine</Button> : null}
          </div>
        </div>
      );
    }
    case "advisory": {
      const a = card.advisory;
      return (
        <div>
          <div className="mb-1 flex items-center gap-2"><SeverityBadge severity={a.severity} /><b className="text-sm">{a.category.replaceAll("_", " ")}</b><Badge>{a.source === "rules" ? "rules" : "rules + AI"}</Badge></div>
          <p className="text-sm">{a.summary}</p>
          <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <div className="mt-2 flex flex-wrap gap-1.5">{a.recommended_actions.map((x) => <Badge key={x} tone="brand">{x.replaceAll("_", " ")}</Badge>)}</div>
          <p className="mt-2 text-xs text-muted-foreground">Advisory only. Acceptance and quarantine are decided by hashes and signatures, never by this text.</p>
        </div>
      );
    }
    case "gaps": return card.missing.length === 0 ? <p className="text-sm">No sequence gaps for <b>{card.device}</b>.</p> : (
      <div className="text-sm"><p>Missing sequence numbers for <b>{card.device}</b> (possible unsent or withheld recordings):</p>
        <p className="mt-1 flex flex-wrap gap-1">{card.missing.slice(0, 40).map((n) => <Badge key={n} tone="warn">{n}</Badge>)}</p></div>
    );
    case "acked": return <p className="flex items-center gap-2 text-sm"><CheckCircle2 className="size-4 text-success" /> Alert <b className="font-mono">{card.id}</b> acknowledged and recorded in the audit log.</p>;
    case "error": return (
      <div className="text-sm"><p className="flex items-center gap-2 font-medium text-danger"><AlertTriangle className="size-4" />{card.status === 403 ? "Not permitted" : card.status === 404 ? "Not found" : "That did not work"}</p>
        <p className="mt-1">{card.message}</p>{card.requestId ? <p className="mt-1 font-mono text-xs text-muted-foreground">request-id {card.requestId}</p> : null}</div>
    );
  }
}
