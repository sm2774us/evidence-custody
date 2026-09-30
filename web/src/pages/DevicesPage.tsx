import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { can } from "@/lib/auth";
import { useSession } from "@/store/session";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ConfirmButton, ErrorState, Field, PageHeader } from "@/components/ui/misc";

const DEV = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

export function DevicesPage() {
  const id = useSession((s) => s.identity)!;
  const [f, setF] = React.useState({ device_id: "", public_key: "", officer_id: "" });
  const [target, setTarget] = React.useState("");
  const [gapId, setGapId] = React.useState("");
  const reg = useMutation({ mutationFn: () => api.registerDevice({ ...f, agency_id: id.agency }), onSuccess: (r) => toast.success(`${r.device_id} registered (pending). A second administrator must activate it.`), onError: (e) => toast.error(e.message) });
  const act = useMutation({ mutationFn: () => api.activateDevice(target.trim()), onSuccess: (r) => toast.success(`${r.device_id} is now active`), onError: (e) => toast.error(e.message) });
  const rev = useMutation({ mutationFn: () => api.revokeDevice(target.trim(), "Revoked via console"), onSuccess: (r) => toast.success(`${r.device_id} revoked`), onError: (e) => toast.error(e.message) });
  const gaps = useMutation({ mutationFn: () => api.gaps(gapId.trim()) });
  const valid = DEV.test(f.device_id) && /^[0-9a-f]{64}$/.test(f.public_key) && DEV.test(f.officer_id);
  const admin = can(id.role, "device:register");
  return (
    <>
      <PageHeader title="Devices" subtitle="Camera identities that may sign uploads. Registration and activation need two different administrators." />
      <div className="grid gap-4 lg:grid-cols-2">
        {admin ? <>
          <Card><CardHeader><CardTitle>1 · Register a camera</CardTitle><Badge>step 1 of 2</Badge></CardHeader><CardContent>
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); reg.mutate(); }}>
              <Field label="Device ID" htmlFor="did"><Input id="did" value={f.device_id} onChange={(e) => setF({ ...f, device_id: e.target.value })} placeholder="cam-0001" /></Field>
              <Field label="Public key (Ed25519, 64 hex characters)" htmlFor="pk" hint="From the camera's secure element enrolment."><Input id="pk" className="font-mono text-xs" value={f.public_key} onChange={(e) => setF({ ...f, public_key: e.target.value.trim().toLowerCase() })} /></Field>
              <Field label="Assigned officer ID" htmlFor="oid"><Input id="oid" value={f.officer_id} onChange={(e) => setF({ ...f, officer_id: e.target.value })} /></Field>
              <Button type="submit" loading={reg.isPending} disabled={!valid}>Register (pending)</Button>
              {reg.isError ? <ErrorState error={reg.error} /> : null}
            </form></CardContent></Card>
          <Card><CardHeader><CardTitle>2 · Activate or revoke</CardTitle><Badge>step 2 of 2</Badge></CardHeader><CardContent className="space-y-3">
            <Field label="Device ID" htmlFor="tid"><Input id="tid" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="cam-0001" /></Field>
            <div className="flex gap-2"><ConfirmButton size="md" variant="primary" label="Activate" confirmLabel="Confirm activate" disabled={!DEV.test(target.trim())} loading={act.isPending} onConfirm={() => act.mutate()} />
              <ConfirmButton size="md" variant="danger" label="Revoke" confirmLabel="Confirm revoke" disabled={!DEV.test(target.trim())} loading={rev.isPending} onConfirm={() => rev.mutate()} /></div>
            {act.isError ? <ErrorState error={act.error} /> : null}{rev.isError ? <ErrorState error={rev.error} /> : null}
            <p className="text-xs text-muted-foreground">You cannot activate a device you registered. Revocation blocks all future uploads from that key.</p>
          </CardContent></Card></> : null}
        {can(id.role, "evidence:read") ? (
          <Card className="lg:col-span-2"><CardHeader><CardTitle>Sequence gap check</CardTitle></CardHeader><CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">Cameras number recordings sequentially. A gap can mean a recording was never uploaded, or was withheld.</p>
            <form className="flex max-w-xl gap-2" onSubmit={(e) => { e.preventDefault(); gaps.mutate(); }}>
              <Input aria-label="Device ID" value={gapId} onChange={(e) => setGapId(e.target.value)} placeholder="cam-0001" />
              <Button type="submit" loading={gaps.isPending} disabled={!DEV.test(gapId.trim())}>Check</Button></form>
            {gaps.isError ? <ErrorState error={gaps.error} /> : null}
            {gaps.data ? (gaps.data.length ? <div className="flex flex-wrap gap-1">{gaps.data.map((n) => <Badge key={n} tone="warn">{n}</Badge>)}</div> : <p className="text-sm text-success">No gaps detected.</p>) : null}
          </CardContent></Card>) : null}
        {!admin && !can(id.role, "evidence:read") ? <p className="text-sm text-muted-foreground">Your role has no device permissions.</p> : null}
      </div>
    </>
  );
}
