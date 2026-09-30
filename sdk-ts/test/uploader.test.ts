import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { DeviceKey, Uploader, buildManifest, canonicalJson } from "../src/uploader.ts";

const vector = JSON.parse(readFileSync(new URL("../../tests/vectors/manifest_vector.json", import.meta.url), "utf8"));

test("canonical JSON and Ed25519 signature match the Python service byte-for-byte", () => {
  const key = new DeviceKey(vector.seed_hex);
  assert.equal(key.publicHex, vector.public_key_hex);
  assert.equal(canonicalJson(vector.manifest), vector.canonical);
  assert.equal(key.sign(Buffer.from(vector.canonical)), vector.signature);
});

test("canonical JSON escapes non-ASCII like Python ensure_ascii", () => {
  assert.equal(canonicalJson({ b: "é✓", a: 1 }), '{"a":1,"b":"\\u00e9\\u2713"}');
});

test("manifest chunking is consistent", () => {
  const key = new DeviceKey(vector.seed_hex);
  const { manifest } = buildManifest(new Uint8Array(2500).fill(7), 1024, {
    deviceId: "cam-1", officerId: "o-1", agencyId: "a-1", sequenceNo: 1,
  }, key);
  assert.equal(manifest.chunk_sha256.length, 3);
  assert.match(manifest.sha256, /^[0-9a-f]{64}$/);
});

test("uploader retries 5xx and refuses receipts with bad signatures", async () => {
  const key = new DeviceKey(vector.seed_hex);
  let calls = 0;
  const fetchImpl: typeof fetch = async (url) => {
    calls++;
    const u = String(url);
    if (calls === 1) return new Response("", { status: 503 });
    if (u.endsWith("/v1/uploads")) return Response.json({ session_id: "up_1" }, { status: 201 });
    if (u.endsWith("/v1/uploads/up_1")) return Response.json({ missing_chunks: [0] });
    if (u.includes("/chunks/")) return Response.json({ status: "stored" });
    return Response.json({ receipt: { evidence_id: "ev_1", sha256: "x", size: 1 }, signature: "00".repeat(64) }, { status: 201 });
  };
  const up = new Uploader({
    baseUrl: "http://x", token: "t", key, servicePublicKeyHex: vector.public_key_hex,
    sleep: async () => {}, fetchImpl,
  });
  await assert.rejects(
    up.upload(new Uint8Array(10), { deviceId: "cam-1", officerId: "o-1", agencyId: "a-1", sequenceNo: 1 }, 16),
    /receipt failed verification/,
  );
  assert.ok(calls > 4);
});
