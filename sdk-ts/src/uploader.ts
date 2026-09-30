import { createHash, createPrivateKey, createPublicKey, randomBytes, sign, verify } from "node:crypto";

/** Deterministic JSON identical to the Python service (sorted keys, no whitespace, ASCII-only). */
export function canonicalJson(v: unknown): string {
  const walk = (x: unknown): unknown => {
    if (Array.isArray(x)) return x.map(walk);
    if (x && typeof x === "object") {
      return Object.fromEntries(
        Object.entries(x as Record<string, unknown>)
          .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
          .map(([k, val]) => [k, walk(val)]),
      );
    }
    return x;
  };
  return JSON.stringify(walk(v)).replace(
    /[\u0080-\uffff]/g,
    (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
  );
}

const PKCS8_ED25519_PREFIX = Buffer.from("302e020100300506032b657004220420", "hex");

export class DeviceKey {
  readonly publicHex: string;
  #key;
  constructor(seedHex: string) {
    this.#key = createPrivateKey({
      key: Buffer.concat([PKCS8_ED25519_PREFIX, Buffer.from(seedHex, "hex")]),
      format: "der",
      type: "pkcs8",
    });
    const spki = createPublicKey(this.#key).export({ format: "der", type: "spki" });
    this.publicHex = spki.subarray(spki.length - 32).toString("hex");
  }
  sign(message: Uint8Array): string {
    return sign(null, message, this.#key).toString("hex");
  }
}

export interface CaptureMeta {
  deviceId: string;
  officerId: string;
  agencyId: string;
  sequenceNo: number;
  caseId?: string | null;
  mediaType?: string;
  retentionClass?: "standard" | "extended" | "permanent";
  idempotencyKey?: string;
  capturedAtMs?: number;
}

const sha256 = (b: Uint8Array): string => createHash("sha256").update(b).digest("hex");

export function buildManifest(data: Uint8Array, chunkSize: number, m: CaptureMeta, key: DeviceKey) {
  const chunks: string[] = [];
  for (let off = 0; off < data.length; off += chunkSize) chunks.push(sha256(data.subarray(off, off + chunkSize)));
  const manifest = {
    schema_version: 1,
    idempotency_key: m.idempotencyKey ?? randomBytes(24).toString("base64url"),
    device_id: m.deviceId,
    officer_id: m.officerId,
    agency_id: m.agencyId,
    case_id: m.caseId ?? null,
    sequence_no: m.sequenceNo,
    captured_at_ms: m.capturedAtMs ?? Date.now(),
    media_type: m.mediaType ?? "video/mp4",
    size: data.length,
    chunk_size: chunkSize,
    chunk_sha256: chunks,
    sha256: sha256(data),
    retention_class: m.retentionClass ?? "standard",
  };
  return { manifest, signature: key.sign(Buffer.from(canonicalJson(manifest))) };
}

export class UploadError extends Error {
  readonly status: number;
  readonly body: Record<string, unknown>;
  constructor(message: string, status = 0, body: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

export interface Receipt {
  receipt: { evidence_id: string; sha256: string; size: number } & Record<string, unknown>;
  signature: string;
}

export interface UploaderOptions {
  baseUrl: string;
  token: string;
  key: DeviceKey;
  servicePublicKeyHex: string; // pin this; do not trust the network for it
  maxRetries?: number;
  sleep?: (ms: number) => Promise<void>;
  fetchImpl?: typeof fetch;
}

export class Uploader {
  private readonly o: UploaderOptions;
  constructor(options: UploaderOptions) {
    this.o = options;
  }

  private async call(method: string, path: string, init: RequestInit = {}): Promise<Response> {
    const f = this.o.fetchImpl ?? fetch;
    const max = this.o.maxRetries ?? 6;
    const sleep = this.o.sleep ?? ((ms) => new Promise<void>((r) => setTimeout(r, ms)));
    for (let attempt = 0; ; attempt++) {
      let res: Response | undefined;
      try {
        res = await f(this.o.baseUrl + path, {
          ...init,
          method,
          headers: { authorization: `Bearer ${this.o.token}`, ...(init.headers as Record<string, string>) },
        });
      } catch {
        res = undefined; // network failure => retry
      }
      if (res && res.status < 500) return res;
      if (attempt >= max) throw new UploadError("service unavailable after retries", res?.status ?? 0);
      await sleep(Math.min(30_000, 250 * 2 ** attempt) * (0.5 + Math.random() / 2));
    }
  }

  async upload(data: Uint8Array, meta: CaptureMeta, chunkSize = 1 << 20): Promise<Receipt> {
    const { manifest, signature } = buildManifest(data, chunkSize, meta, this.o.key);
    const created = await this.call("POST", "/v1/uploads", {
      body: JSON.stringify({ manifest, signature }),
      headers: { "content-type": "application/json" },
    });
    if (created.status !== 201 && created.status !== 200) {
      throw new UploadError("create failed", created.status, (await created.json()) as Record<string, unknown>);
    }
    const { session_id: sid } = (await created.json()) as { session_id: string };
    const status = (await (await this.call("GET", `/v1/uploads/${sid}`)).json()) as { missing_chunks: number[] };
    for (const idx of status.missing_chunks) await this.sendChunk(sid, idx, data.subarray(idx * chunkSize, (idx + 1) * chunkSize));
    const done = await this.call("POST", `/v1/uploads/${sid}/complete`);
    const body = (await done.json()) as Receipt & Record<string, unknown>;
    if (done.status !== 201 && done.status !== 200) throw new UploadError("upload not acknowledged", done.status, body);
    const ok = verify(
      null,
      Buffer.from(canonicalJson(body.receipt)),
      createPublicKey({
        key: Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), Buffer.from(this.o.servicePublicKeyHex, "hex")]),
        format: "der",
        type: "spki",
      }),
      Buffer.from(body.signature, "hex"),
    );
    if (!ok || body.receipt.sha256 !== manifest.sha256) throw new UploadError("receipt failed verification");
    return body; // only now is it safe for the camera to purge its local copy
  }

  private async sendChunk(sid: string, idx: number, chunk: Uint8Array): Promise<void> {
    for (let attempt = 0; attempt <= (this.o.maxRetries ?? 6); attempt++) {
      const r = await this.call("PUT", `/v1/uploads/${sid}/chunks/${idx}`, { body: chunk as BodyInit });
      if (r.status === 200) return;
      const b = (await r.json()) as Record<string, unknown>;
      if (!(r.status === 422 && b["retryable"])) throw new UploadError("chunk rejected", r.status, b);
    }
    throw new UploadError(`chunk ${idx} failed after retries`);
  }
}
