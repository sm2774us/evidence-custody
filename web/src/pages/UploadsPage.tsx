import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Check, CircleDot, Search, Sparkles, X } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { can } from "@/lib/auth";
import type { AuditEntry } from "@/lib/types";
import { cn, fmtTime } from "@/lib/utils";
import { usePrefs, useSession } from "@/store/session";
import { SeverityBadge, Badge, StateBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input, Select } from "@/components/ui/input";
import { ConfirmButton, EmptyState, ErrorState, Field, PageHeader, Skeleton } from "@/components/ui/misc";
import { Link } from "@tanstack/react-router";

const ID_RE = /^up_[a-f0-9]{16,24}$/i;
const STEPS = ["created", "uploading", "verifying", "verified", "available"] as const;

export function UploadLookupPage() {
  const nav = useNavigate();
  const recents = usePrefs((s) => s.recents).filter((r) => r.startsWith("up_"));
  const [id, setId] = React.useState("");
  const bad = id.trim() !== "" && !ID_RE.test(id.trim());
  return (
    <>
      <PageHeader title="Uploads" subtitle="Inspect an upload session: progress, verification outcome, and quarantine review." />
      <Card className="max-w-2xl"><CardContent>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (!bad && id.trim()) void nav({ to: "/uploads/$id", params: { id: id.trim().toLowerCase() } }); }}>
          <div className="flex-1"><Input aria-label="Upload session ID" aria-invalid={bad} className="font-mono" placeholder="up_0123456789abcdef0123" value={id} onChange={(e) => setId(e.target.value)} />
            {bad ? <p role="alert" className="mt-1 text-xs text-danger">Session IDs look like up_ followed by 20 hex characters.</p> : null}</div>
          <Button type="submit" disabled={!id.trim() || bad}><Search className="size-4" /> Inspect</Button>
        </form>
      </CardContent></Card>
      {recents.length ? <ul className="mt-4 grid gap-2 sm:grid-cols-2">{recents.map((r) => <li key={r}><Button variant="outline" className="w-full justify-start font-mono text-xs" onClick={() => void nav({ to: "/uploads/$id", params: { id: r } })}>{r}</Button></li>)}</ul> : null}
    </>
  );
}

const cols: ColumnDef<AuditEntry, unknown>[] = [
  { accessorKey: "seq", header: "#" },
  { accessorKey: "ts_ms", header: "When", cell: (c) => <span className="whitespace-nowrap text-xs">{fmtTime(c.getValue<number>())}</span> },
  { accessorKey: "action", header: "Event", cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
  { accessorKey: "actor", header: "Actor" },
  { id: "detail", header: "Detail", enableSorting: false, cell: (c) => <code className="line-clamp-2 break-all text-xs text-muted-foreground">{JSON.stringify(c.row.original.detail)}</code> },
];

export function UploadDetailPage() {
  const { id } = useParams({ strict: false }) as { id: string };
  const role = useSession((s) => s.identity?.role);
  const remember = usePrefs((s) => s.remember);
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["upload", id], queryFn: () => api.inspectUpload(id), refetchInterval: (s) => (s.state.data && ["created", "uploading", "verifying"].includes(s.state.data.state) ? 3000 : false) });
  React.useEffect(() => { if (q.isSuccess) remember(id); }, [q.isSuccess, id, remember]);
  const [note, setNote] = React.useState("");
  const [decision, setDecision] = React.useState<"retry_authorized" | "retain_for_investigation">("retain_for_investigation");
  const triage = useMutation({ mutationFn: () => api.triage(id), onError: (e) => toast.error(e.message) });
  const disp = useMutation({
    mutationFn: () => api.disposition(id, decision, note.trim()),
    onSuccess: () => { toast.success("Disposition recorded in the chain of custody"); void qc.invalidateQueries({ queryKey: ["upload", id] }); },
    onError: (e) => toast.error(e.message),
  });
  if (q.isLoading) return <div className="space-y-3"><Skeleton className="h-10 w-72" /><Skeleton className="h-48" /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const u = q.data!;
  const quarantined = u.state === "quarantined";
  const idx = STEPS.indexOf(u.state as (typeof STEPS)[number]);
  const got = new Set(u.received_chunks);
  return (
    <>
      <PageHeader title="Upload session" subtitle={u.session_id} actions={<StateBadge state={u.state} />} />
      <Card><CardHeader><CardTitle>Workflow</CardTitle></CardHeader><CardContent>
        <ol className="flex flex-wrap items-center gap-2" aria-label="Upload state">
          {STEPS.map((s, i) => {
            const done = !quarantined && idx >= 0 && i <= idx;
            return <li key={s} className="flex items-center gap-2"><span className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs", done ? "border-success/40 bg-success/10 text-success" : "text-muted-foreground")}>
              {done ? <Check className="size-3" /> : <CircleDot className="size-3" />}{s}</span>{i < STEPS.length - 1 ? <span className="text-muted-foreground">›</span> : null}</li>;
          })}
          {quarantined ? <li><Badge tone="danger"><X className="size-3" /> quarantined</Badge></li> : null}
          {u.state === "expired" ? <li><Badge tone="warn">expired</Badge></li> : null}
        </ol>
        {u.failure_reason ? <p className="mt-3 text-sm text-danger">Reason: {u.failure_reason}</p> : null}
        {u.evidence_id ? <p className="mt-3 text-sm">Evidence: <Link className="font-mono underline" to="/evidence/$id" params={{ id: u.evidence_id }}>{u.evidence_id}</Link></p> : null}
        <h3 className="mb-2 mt-5 text-xs font-medium text-muted-foreground">Chunks: {got.size} of {u.chunk_count} received</h3>
        <div className="flex max-h-32 flex-wrap gap-1 overflow-auto" role="img" aria-label={`${got.size} of ${u.chunk_count} chunks received`}>
          {Array.from({ length: Math.min(u.chunk_count, 600) }, (_, i) => <span key={i} title={`chunk ${i}`} className={cn("size-3 rounded-sm", got.has(i) ? "bg-success" : "bg-muted")} />)}
        </div>
      </CardContent></Card>

      {quarantined ? (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          {can(role, "triage:run") ? (
            <Card><CardHeader><CardTitle>Triage advisory</CardTitle><Button size="sm" loading={triage.isPending} onClick={() => triage.mutate()}><Sparkles className="size-3.5" /> Explain</Button></CardHeader><CardContent>
              {triage.data ? <div className="space-y-2 text-sm"><div className="flex items-center gap-2"><SeverityBadge severity={triage.data.severity} /><b>{triage.data.category.replaceAll("_", " ")}</b><Badge>{triage.data.source === "rules" ? "rules" : "rules + AI"}</Badge></div>
                <p>{triage.data.summary}</p><ul className="list-disc pl-5 text-muted-foreground">{triage.data.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                <div className="flex flex-wrap gap-1.5">{triage.data.recommended_actions.map((a) => <Badge key={a} tone="brand">{a.replaceAll("_", " ")}</Badge>)}</div>
                <p className="text-xs text-muted-foreground">Advisory only. The quarantine was decided by hash verification.</p></div>
                : <EmptyState title="Ask for an explanation" hint="Deterministic rules always answer; an AI summary is added only when the operator enabled it." />}
            </CardContent></Card>) : null}
          {can(role, "quarantine:review") ? (
            <Card><CardHeader><CardTitle>Custodian review</CardTitle></CardHeader><CardContent className="space-y-3">
              <Field label="Decision" htmlFor="dec"><Select id="dec" value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)}>
                <option value="retain_for_investigation">Retain for investigation</option><option value="retry_authorized">Authorize a new upload attempt</option></Select></Field>
              <Field label="Note (min 8 characters)" htmlFor="note"><Input id="note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why this decision" /></Field>
              <ConfirmButton label="Record decision" confirmLabel="Confirm and record" variant="primary" size="md" disabled={note.trim().length < 8} loading={disp.isPending} onConfirm={() => disp.mutate()} />
              <p className="text-xs text-muted-foreground">The received bytes stay preserved either way. Your decision joins the chain of custody.</p>
            </CardContent></Card>) : null}
        </div>) : null}

      <Card className="mt-4"><CardHeader><CardTitle>Audit trail</CardTitle></CardHeader><CardContent><DataTable data={u.audit} columns={cols} pageSize={10} searchPlaceholder="Filter events…" /></CardContent></Card>
    </>
  );
}
