import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Download, FileSearch, Lock, ScrollText, ShieldCheck } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { can } from "@/lib/auth";
import { sha256Hex, verifySignedObject } from "@/lib/crypto";
import type { AuditEntry, Evidence } from "@/lib/types";
import { fmtBytes, fmtTime } from "@/lib/utils";
import { usePrefs, useSession } from "@/store/session";
import { Badge, StateBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input, Select, Textarea } from "@/components/ui/input";
import { ConfirmButton, EmptyState, ErrorState, Field, HashChip, PageHeader, Skeleton } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const ID_RE = /^ev_[a-f0-9]{16,24}$/i;
const MAX_BROWSER_BYTES = 256 * 1024 * 1024;

export function EvidenceLookupPage() {
  const nav = useNavigate();
  const recents = usePrefs((s) => s.recents).filter((r) => r.startsWith("ev_"));
  const [id, setId] = React.useState("");
  const bad = id.trim() !== "" && !ID_RE.test(id.trim());
  return (
    <>
      <PageHeader title="Evidence" subtitle="Look up a recording by its evidence ID (from the camera's signed receipt)." />
      <Card className="max-w-2xl"><CardContent>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (!bad && id.trim()) void nav({ to: "/evidence/$id", params: { id: id.trim().toLowerCase() } }); }}>
          <div className="flex-1"><Input aria-label="Evidence ID" aria-invalid={bad} placeholder="ev_0123456789abcdef0123" className="font-mono" value={id} onChange={(e) => setId(e.target.value)} />
            {bad ? <p role="alert" className="mt-1 text-xs text-danger">Evidence IDs look like ev_ followed by 20 hex characters.</p> : null}</div>
          <Button type="submit" disabled={!id.trim() || bad}><FileSearch className="size-4" /> Open</Button>
        </form>
      </CardContent></Card>
      <h2 className="mb-2 mt-6 text-sm font-semibold">Recently opened</h2>
      {recents.length === 0 ? <EmptyState title="Nothing opened yet" hint="Items you open appear here for quick return (kept in this browser only)." />
        : <ul className="grid gap-2 sm:grid-cols-2">{recents.map((r) => <li key={r}><Button variant="outline" className="w-full justify-start font-mono text-xs" onClick={() => void nav({ to: "/evidence/$id", params: { id: r } })}>{r}</Button></li>)}</ul>}
    </>
  );
}

function AccessPanel({ ev }: { ev: Evidence }) {
  const [reason, setReason] = React.useState("");
  const [url, setUrl] = React.useState<string | null>(null);
  React.useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  const tooBig = ev.size > MAX_BROWSER_BYTES;
  const m = useMutation({
    mutationFn: async () => {
      const { blob, headerSha256 } = await api.content(ev.evidence_id, reason.trim());
      const actual = await sha256Hex(await blob.arrayBuffer());
      return { blob, actual, headerSha256 };
    },
    onSuccess: (r) => { setUrl((old) => { if (old) URL.revokeObjectURL(old); return URL.createObjectURL(r.blob); }); },
  });
  const ok = m.data && m.data.actual === ev.sha256 && (!m.data.headerSha256 || m.data.headerSha256 === ev.sha256);
  const kind = ev.media_type.split("/")[0];
  return (
    <Card><CardHeader><CardTitle>Controlled access</CardTitle><Badge tone="warn"><Lock className="size-3" /> logged</Badge></CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">Every retrieval is recorded with your identity and the reason below. The file is hashed in your browser and compared with the SHA-256 attested by the camera.</p>
        <Field label="Reason for access (required, min 8 characters)" htmlFor="reason"><Textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Prosecutor request, case 26-0142" /></Field>
        {tooBig ? <p role="alert" className="text-sm text-warning">This file is {fmtBytes(ev.size)}, above the {fmtBytes(MAX_BROWSER_BYTES)} in-browser verification limit. Use the SDK or CLI to retrieve it.</p> : null}
        <Button loading={m.isPending} disabled={reason.trim().length < 8 || tooBig || !can(useSession.getState().identity?.role, "evidence:download")} onClick={() => m.mutate()}><Download className="size-4" /> Retrieve and verify</Button>
        {m.isError ? <ErrorState error={m.error} /> : null}
        {m.data ? (
          <div className="space-y-3">
            <div role="status" className={`rounded-lg border p-3 text-sm ${ok ? "border-success/40 bg-success/10" : "border-danger/50 bg-danger/10"}`}>
              {ok ? <><b className="text-success">Verified.</b> The bytes received hash to the attested SHA-256 ({fmtBytes(m.data.blob.size)}).</>
                : <><b className="text-danger">HASH MISMATCH.</b> Do not rely on this copy. The event has been recorded; notify your custodian.<div className="mt-1 font-mono text-xs">expected {ev.sha256}<br />got {m.data.actual}</div></>}
            </div>
            {ok && url ? (
              <>
                {kind === "video" ? <video controls src={url} className="max-h-96 w-full rounded-lg bg-black" /> : kind === "audio" ? <audio controls src={url} className="w-full" /> : kind === "image" ? <img src={url} alt="Evidence preview" className="max-h-96 rounded-lg" /> : null}
                <Button variant="outline" asChild><a href={url} download={`${ev.evidence_id}`}><Download className="size-4" /> Save copy</a></Button>
              </>
            ) : null}
          </div>
        ) : null}
      </CardContent></Card>
  );
}

const evCols: ColumnDef<AuditEntry, unknown>[] = [
  { accessorKey: "seq", header: "#" },
  { accessorKey: "ts_ms", header: "When", cell: (c) => <span className="whitespace-nowrap text-xs">{fmtTime(c.getValue<number>())}</span> },
  { accessorKey: "actor", header: "Actor", cell: (c) => <span>{c.getValue<string>()} <span className="text-xs text-muted-foreground">({c.row.original.actor_role})</span></span> },
  { accessorKey: "action", header: "Action", cell: (c) => <span className="font-mono text-xs">{c.getValue<string>()}</span> },
  { accessorKey: "entry_hash", header: "Entry hash", enableSorting: false, cell: (c) => <HashChip value={c.getValue<string>()} /> },
];

function CustodyPanel({ ev }: { ev: Evidence }) {
  const m = useMutation({
    mutationFn: async () => {
      const [view, key] = await Promise.all([api.custody(ev.evidence_id), api.keys()]);
      return { view, sig: await verifySignedObject(key.public_key, view.signature, view.report), key };
    },
  });
  const r = m.data?.view.report;
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(m.data!.view, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `custody-${ev.evidence_id}.json`; a.click(); URL.revokeObjectURL(a.href);
  };
  return (
    <Card><CardHeader><CardTitle>Chain-of-custody report</CardTitle>
      <div className="flex gap-2">{r ? <Button size="sm" variant="outline" onClick={exportJson}><Download className="size-3.5" /> Export signed JSON</Button> : null}
        <Button size="sm" loading={m.isPending} onClick={() => m.mutate()}><ScrollText className="size-3.5" /> {r ? "Regenerate" : "Generate"}</Button></div></CardHeader>
      <CardContent className="space-y-4">
        {!r && !m.isPending && !m.isError ? <EmptyState title="No report yet" hint="Generating re-hashes the stored original, verifies the audit chain and signs the result. The generation itself is logged." /> : null}
        {m.isPending ? <Skeleton className="h-24" /> : null}
        {m.isError ? <ErrorState error={m.error} onRetry={() => m.mutate()} /> : null}
        {r && m.data ? (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge tone={r.fixity_ok ? "ok" : "danger"}>{r.fixity_ok ? "Fixity: stored bytes match" : "FIXITY FAILED"}</Badge>
              <Badge tone={r.audit_chain.ok ? "ok" : "danger"}>{r.audit_chain.ok ? `Audit chain OK (${r.audit_chain.entries})` : "AUDIT CHAIN BROKEN"}</Badge>
              <Badge tone={m.data.sig === "valid" ? "ok" : m.data.sig === "invalid" ? "danger" : "warn"}>
                {m.data.sig === "valid" ? `Signature valid (key ${m.data.key.key_id})` : m.data.sig === "invalid" ? "SIGNATURE INVALID" : "Signature not checked: browser lacks Ed25519"}</Badge>
            </div>
            <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              <div className="flex justify-between"><dt className="text-muted-foreground">Recorded SHA-256</dt><dd><HashChip value={r.sha256_recorded} /></dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">SHA-256 now</dt><dd><HashChip value={r.sha256_now} /></dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Generated</dt><dd>{fmtTime(r.generated_at_ms)}</dd></div>
              <div className="flex justify-between"><dt className="text-muted-foreground">Derivatives</dt><dd>{r.derivatives.length}</dd></div>
            </dl>
            <DataTable data={r.custody_events} columns={evCols} pageSize={10} searchPlaceholder="Filter events…" />
          </>
        ) : null}
      </CardContent></Card>
  );
}

function ActionsPanel({ ev, refetch }: { ev: Evidence; refetch: () => void }) {
  const role = useSession((s) => s.identity?.role);
  const [kind, setKind] = React.useState("clip");
  const [file, setFile] = React.useState<File | null>(null);
  const [caseRef, setCaseRef] = React.useState("");
  const [why, setWhy] = React.useState("");
  const done = (msg: string) => () => { toast.success(msg); refetch(); };
  const deriv = useMutation({ mutationFn: () => api.derivative(ev.evidence_id, kind, file!, {}), onSuccess: done("Derivative recorded; the original is untouched"), onError: (e) => toast.error(e.message) });
  const req = useMutation({ mutationFn: () => api.requestHold(ev.evidence_id, caseRef.trim(), why.trim()), onSuccess: done("Hold requested; a legal officer must approve"), onError: (e) => toast.error(e.message) });
  const appr = useMutation({ mutationFn: (h: string) => api.approveHold(h), onSuccess: done("Hold approved and applied"), onError: (e) => toast.error(e.message) });
  const rel = useMutation({ mutationFn: (h: string) => api.releaseHold(h, "Released via console"), onSuccess: done("Hold released"), onError: (e) => toast.error(e.message) });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader><CardTitle>Legal holds</CardTitle></CardHeader><CardContent className="space-y-3">
        {ev.legal_holds.length === 0 ? <p className="text-sm text-muted-foreground">No holds on this evidence.</p> : ev.legal_holds.map((h) => (
          <div key={h.hold_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-2 text-sm">
            <span><b>{h.case_ref}</b> <StateBadge state={h.status} /></span>
            <span className="flex gap-2">
              {h.status === "pending" && can(role, "hold:approve") ? <ConfirmButton label="Approve" onConfirm={() => appr.mutate(h.hold_id)} loading={appr.isPending} /> : null}
              {h.status === "active" && can(role, "hold:release") ? <ConfirmButton label="Release" variant="danger" onConfirm={() => rel.mutate(h.hold_id)} loading={rel.isPending} /> : null}
            </span>
          </div>))}
        {can(role, "hold:request") ? (
          <form className="space-y-2 border-t pt-3" onSubmit={(e) => { e.preventDefault(); req.mutate(); }}>
            <Field label="Case reference" htmlFor="caseref"><Input id="caseref" value={caseRef} onChange={(e) => setCaseRef(e.target.value)} placeholder="CASE-2026-0142" /></Field>
            <Field label="Reason (min 8 characters)" htmlFor="holdwhy"><Input id="holdwhy" value={why} onChange={(e) => setWhy(e.target.value)} /></Field>
            <Button type="submit" size="sm" loading={req.isPending} disabled={!caseRef.trim() || why.trim().length < 8}>Request hold</Button>
            <p className="text-xs text-muted-foreground">Two-person rule: a different legal officer must approve.</p>
          </form>) : null}
      </CardContent></Card>
      <Card><CardHeader><CardTitle>Derivatives</CardTitle></CardHeader><CardContent className="space-y-3">
        <p className="text-sm text-muted-foreground">Clips, redactions and transcodes reference this original by hash. They can never replace it.</p>
        {can(role, "derivative:create") ? (
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); deriv.mutate(); }}>
            <Field label="Kind" htmlFor="dkind"><Select id="dkind" value={kind} onChange={(e) => setKind(e.target.value)}>{["clip", "redaction", "transcode", "thumbnail", "transcript"].map((k) => <option key={k}>{k}</option>)}</Select></Field>
            <Field label="File" htmlFor="dfile"><Input id="dfile" type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="py-1.5" /></Field>
            <Button type="submit" size="sm" loading={deriv.isPending} disabled={!file}>Upload derivative</Button>
          </form>) : <p className="text-sm text-muted-foreground">Your role cannot create derivatives.</p>}
      </CardContent></Card>
    </div>
  );
}

export function EvidenceDetailPage() {
  const { id } = useParams({ strict: false }) as { id: string };
  const { tab } = useSearch({ strict: false }) as { tab?: string };
  const nav = useNavigate();
  const remember = usePrefs((s) => s.remember);
  const role = useSession((s) => s.identity?.role);
  const q = useQuery({ queryKey: ["evidence", id], queryFn: () => api.evidence(id) });
  React.useEffect(() => { if (q.isSuccess) remember(id); }, [q.isSuccess, id, remember]);
  if (q.isLoading) return <div className="space-y-3"><Skeleton className="h-10 w-72" /><Skeleton className="h-64" /></div>;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const ev = q.data!;
  return (
    <>
      <PageHeader title="Evidence" subtitle={ev.evidence_id} actions={<StateBadge state={ev.state} />} />
      <Tabs value={tab ?? "overview"} onValueChange={(t) => void nav({ to: "/evidence/$id", params: { id }, search: { tab: t } })}>
        <TabsList><TabsTrigger value="overview">Overview</TabsTrigger>{can(role, "evidence:download") ? <TabsTrigger value="access">Access</TabsTrigger> : null}
          {can(role, "custody:report") ? <TabsTrigger value="custody">Custody report</TabsTrigger> : null}<TabsTrigger value="actions">Holds and derivatives</TabsTrigger></TabsList>
        <TabsContent value="overview"><Card><CardContent><dl className="grid gap-3 text-sm sm:grid-cols-2">
          {([["SHA-256", <HashChip key="h" value={ev.sha256} full />], ["Size", `${fmtBytes(ev.size)} (${ev.size.toLocaleString()} bytes)`], ["Media type", ev.media_type], ["Case", ev.case_id ?? "—"],
            ["Device", ev.device_id], ["Officer", ev.officer_id], ["Sequence no.", ev.sequence_no], ["Captured (device clock)", fmtTime(ev.captured_at_ms)], ["Received (server clock)", fmtTime(ev.received_at_ms)],
            ["Retained until", fmtTime(ev.retention_until_ms)], ["Storage version", ev.version_id], ["Agency", ev.agency_id]] as [string, React.ReactNode][])
            .map(([k, v]) => <div key={k} className="min-w-0"><dt className="text-xs text-muted-foreground">{k}</dt><dd className="mt-0.5 break-words">{v}</dd></div>)}
        </dl><p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-3.5 text-success" /> The original is write-once. Retention can be extended but never shortened.</p></CardContent></Card></TabsContent>
        <TabsContent value="access"><AccessPanel ev={ev} /></TabsContent>
        <TabsContent value="custody"><CustodyPanel ev={ev} /></TabsContent>
        <TabsContent value="actions"><ActionsPanel ev={ev} refetch={() => void q.refetch()} /></TabsContent>
      </Tabs>
    </>
  );
}
