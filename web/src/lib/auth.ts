export type Role = "device" | "reader" | "custodian" | "legal" | "auditor" | "admin";

/** Mirror of the service's PERMISSIONS table. UI gating is convenience only; the API enforces. */
export const PERMISSIONS: Record<Role, readonly string[]> = {
  device: ["upload:create", "upload:write", "upload:read"],
  reader: ["evidence:read", "evidence:download"],
  custodian: ["evidence:read", "evidence:download", "derivative:create", "hold:request", "quarantine:review",
    "custody:report", "triage:run", "alerts:read", "alerts:ack", "upload:inspect"],
  legal: ["evidence:read", "hold:approve", "hold:release", "custody:report"],
  auditor: ["audit:read", "audit:verify", "custody:report", "alerts:read", "alerts:ack", "triage:run",
    "evidence:read", "upload:inspect", "audit:scan"],
  admin: ["device:register", "device:activate", "device:revoke", "principal:revoke", "audit:checkpoint"],
};

export interface Identity { sub: string; role: Role; agency: string; exp: number; jti: string }

const ROLES = new Set<string>(Object.keys(PERMISSIONS));

export function decodeToken(token: string): Identity | null {
  try {
    const body = token.trim().split(".")[0];
    if (!body) return null;
    const b64 = body.replace(/-/g, "+").replace(/_/g, "/");
    const json = new TextDecoder().decode(Uint8Array.from(atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4)), (c) => c.charCodeAt(0)));
    const p = JSON.parse(json) as Partial<Identity>;
    if (!p.sub || !p.agency || typeof p.exp !== "number" || !p.role || !ROLES.has(p.role)) return null;
    return { sub: p.sub, role: p.role, agency: p.agency, exp: p.exp, jti: p.jti ?? "" };
  } catch {
    return null;
  }
}

export const can = (role: Role | undefined, perm: string): boolean => !!role && PERMISSIONS[role].includes(perm);
export const secondsLeft = (id: Identity, now = Date.now()): number => Math.floor(id.exp - now / 1000);
