import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { AlertOctagon, Clock, Database, FileWarning, MessageSquare, ShieldCheck, ShieldAlert, Stamp } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { can } from "@/lib/auth";
import { parseMetrics } from "@/lib/metrics";
import { relTime } from "@/lib/utils";
import { useSession } from "@/store/session";
import { SeverityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, PageHeader, Skeleton } from "@/components/ui/misc";

function Kpi({ icon, label, value, tone, loading }: { icon: React.ReactNode; label: string; value: React.ReactNode; tone?: "danger" | "ok"; loading?: boolean }) {
  return (
    <Card><CardContent className="flex items-center gap-3">
      <span className={`grid size-10 place-items-center rounded-lg bg-muted ${tone === "danger" ? "text-danger" : tone === "ok" ? "text-success" : "text-accent"}`}>{icon}</span>
      <div><div className="text-xs text-muted-foreground">{label}</div>{loading ? <Skeleton className="mt-1 h-6 w-16" /> : <div className="text-xl font-semibold tabular-nums">{value}</div>}</div>
    </CardContent></Card>
  );
}

export function DashboardPage() {
  const id = useSession((s) => s.identity)!;
  const qc = useQueryClient();
  const ready = useQuery({ queryKey: ["ready"], queryFn: api.ready, refetchInterval: 15_000, retry: false });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api.metricsText().then(parseMetrics), refetchInterval: 15_000 });
  const canAlerts = can(id.role, "alerts:read");
  const alerts = useQuery({ queryKey: ["alerts", "open"], queryFn: () => api.alerts("open"), enabled: canAlerts, refetchInterval: 30_000 });
  const verify = useMutation({
    mutationFn: api.auditVerify,
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["ready"] }); if (r.ok) toast.success(`Audit chain intact (${r.entries} entries)`); else toast.error(`Audit chain BROKEN: ${r.error}`); },
    onError: (e) => toast.error(e.message),
  });
  const checkpoint = useMutation({
    mutationFn: api.auditCheckpoint,
    onSuccess: () => toast.success("Signed checkpoint recorded. Export it to your independent anchor store."),
    onError: (e) => toast.error(e.message),
  });
  const m = metrics.data ?? {};
  const openAlerts = canAlerts ? (alerts.data?.length ?? 0) : (m.custody_open_alerts ?? 0);

  return (
    <>
      <PageHeader title="Operations dashboard" subtitle={`${id.agency} · signed in as ${id.sub} (${id.role})`}
        actions={<>
          {can(id.role, "audit:verify") ? <Button variant="outline" loading={verify.isPending} onClick={() => verify.mutate()}><ShieldCheck className="size-4" /> Verify audit chain</Button> : null}
          {can(id.role, "audit:checkpoint") ? <Button variant="outline" loading={checkpoint.isPending} onClick={() => checkpoint.mutate()}><Stamp className="size-4" /> Sign audit checkpoint</Button> : null}
          <Button asChild><Link to="/assistant"><MessageSquare className="size-4" /> Ask the assistant</Link></Button>
        </>} />
      {ready.data && !ready.data.ready ? (
        <div role="alert" className="mb-4 flex items-start gap-3 rounded-lg border border-danger/50 bg-danger/10 p-4">
          <ShieldAlert className="mt-0.5 size-5 text-danger" /><div><b>Audit integrity failure.</b><p className="text-sm">{ready.data.audit_error}. Treat as a security incident and follow the runbook. Do not alter data.</p></div>
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi icon={<Database className="size-5" />} label="Evidence stored" value={m.custody_evidence_stored_total ?? 0} loading={metrics.isLoading} />
        <Kpi icon={<AlertOctagon className="size-5" />} label="Open alerts" value={openAlerts} tone={openAlerts ? "danger" : "ok"} loading={metrics.isLoading && !canAlerts} />
        <Kpi icon={<FileWarning className="size-5" />} label="Quarantined uploads" value={m.custody_quarantined_sessions ?? 0} tone={(m.custody_quarantined_sessions ?? 0) ? "danger" : "ok"} loading={metrics.isLoading} />
        <Kpi icon={<Clock className="size-5" />} label="Oldest open upload" value={`${Math.round(m.custody_oldest_open_upload_age_seconds ?? 0)}s`} loading={metrics.isLoading} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>Open alerts</CardTitle>{canAlerts ? <Button asChild size="sm" variant="ghost"><Link to="/alerts">View all</Link></Button> : null}</CardHeader>
          <CardContent>
            {!canAlerts ? <EmptyState title="Alerts are not available to your role" hint="Auditors and custodians can review and acknowledge alerts." />
              : alerts.isLoading ? <div className="space-y-2"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
              : alerts.isError ? <ErrorState error={alerts.error} onRetry={() => alerts.refetch()} />
              : alerts.data!.length === 0 ? <EmptyState title="All clear" hint="No open integrity or access alerts." />
              : <ul className="divide-y">{alerts.data!.slice(0, 6).map((a) => (
                  <li key={a.alert_id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                    <SeverityBadge severity={a.severity} /><b>{a.kind}</b><span className="min-w-0 flex-1 truncate text-muted-foreground">{a.detail.advisory?.summary}</span>
                    <span className="text-xs text-muted-foreground">{relTime(a.ts_ms)}</span>
                  </li>))}</ul>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Integrity signals</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {[["Audit entries", ready.data?.audit_entries ?? "—"], ["Chunks rejected", m.custody_chunks_total ?? 0], ["Hash mismatches", m.custody_hash_mismatch_total ?? 0],
              ["Idempotent replays", m.custody_idempotent_replays_total ?? 0], ["Access denials", m.custody_authz_denied_total ?? 0], ["Evidence accesses", m.custody_evidence_access_total ?? 0]]
              .map(([k, v]) => <div key={String(k)} className="flex justify-between"><span className="text-muted-foreground">{k}</span><span className="tabular-nums">{v}</span></div>)}
            <p className="pt-2 text-xs text-muted-foreground">Chunk counter includes stored, duplicate and rejected. Refreshes every 15 s.</p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
