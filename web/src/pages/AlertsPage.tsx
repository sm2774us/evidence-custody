import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { RefreshCw } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { can } from "@/lib/auth";
import type { Alert } from "@/lib/types";
import { fmtTime, relTime } from "@/lib/utils";
import { useSession } from "@/store/session";
import { Badge, SeverityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { ConfirmButton, ErrorState, HashChip, PageHeader, Skeleton } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const ORDER = { critical: 0, high: 1, medium: 2, low: 3 } as const;

export function AlertsPage() {
  const role = useSession((s) => s.identity?.role);
  const qc = useQueryClient();
  const [status, setStatus] = React.useState<"open" | "acknowledged">("open");
  const [sel, setSel] = React.useState<Alert | null>(null);
  const q = useQuery({ queryKey: ["alerts", status], queryFn: () => api.alerts(status), refetchInterval: 30_000 });
  const ack = useMutation({
    mutationFn: (id: string) => api.ackAlert(id),
    onSuccess: () => { toast.success("Alert acknowledged and recorded"); void qc.invalidateQueries({ queryKey: ["alerts"] }); setSel(null); },
    onError: (e) => toast.error(e.message),
  });
  const cols = React.useMemo<ColumnDef<Alert, unknown>[]>(() => [
    { accessorKey: "severity", header: "Severity", sortingFn: (a, b) => ORDER[a.original.severity] - ORDER[b.original.severity], cell: (c) => <SeverityBadge severity={c.getValue<string>()} /> },
    { accessorKey: "kind", header: "Kind", cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
    { id: "summary", header: "Summary", enableSorting: false, cell: (c) => <span className="line-clamp-2 max-w-md text-muted-foreground">{c.row.original.detail.advisory?.summary}</span> },
    { accessorKey: "object_id", header: "Object", enableSorting: false, cell: (c) => <HashChip value={c.getValue<string>()} /> },
    { accessorKey: "ts_ms", header: "Raised", cell: (c) => <span title={fmtTime(c.getValue<number>())} className="whitespace-nowrap text-xs">{relTime(c.getValue<number>())}</span> },
  ], []);
  const a = sel?.detail.advisory;
  return (
    <>
      <PageHeader title="Alerts" subtitle="Integrity and access anomalies raised by deterministic checks. Rules decide; AI only explains."
        actions={<Button variant="outline" onClick={() => void q.refetch()} loading={q.isFetching}><RefreshCw className="size-4" /> Refresh</Button>} />
      <Tabs value={status} onValueChange={(v) => setStatus(v as typeof status)} className="mb-4"><TabsList><TabsTrigger value="open">Open</TabsTrigger><TabsTrigger value="acknowledged">Acknowledged</TabsTrigger></TabsList></Tabs>
      {q.isLoading ? <Skeleton className="h-64" /> : q.isError ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : <DataTable data={q.data!} columns={cols} onRowClick={setSel} empty={status === "open" ? "No open alerts. All clear." : "Nothing acknowledged yet."} />}
      <Dialog open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <DialogContent title={sel?.kind ?? "Alert"} description={sel ? `Raised ${fmtTime(sel.ts_ms)}` : undefined}>
          {sel && a ? (
            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2"><SeverityBadge severity={sel.severity} /><Badge>{a.category.replaceAll("_", " ")}</Badge><Badge>{a.source === "rules" ? "rules" : `rules + AI (${a.model})`}</Badge></div>
              <p>{a.summary}</p>
              <ul className="list-disc pl-5 text-muted-foreground">{a.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              <div><div className="mb-1 text-xs text-muted-foreground">Recommended actions</div><div className="flex flex-wrap gap-1.5">{a.recommended_actions.map((x) => <Badge key={x} tone="brand">{x.replaceAll("_", " ")}</Badge>)}</div></div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">Object <HashChip value={sel.object_id} /></div>
              {sel.status === "open" && can(role, "alerts:ack") ? <ConfirmButton size="md" variant="primary" label="Acknowledge alert" confirmLabel="Confirm acknowledge" loading={ack.isPending} onConfirm={() => ack.mutate(sel.alert_id)} />
                : sel.status !== "open" ? <p className="text-xs text-muted-foreground">Acknowledged by {sel.acked_by} {sel.acked_at_ms ? relTime(sel.acked_at_ms) : ""}.</p> : null}
            </div>) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
