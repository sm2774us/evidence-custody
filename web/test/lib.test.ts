import { describe, expect, it } from "vitest";
import vector from "./fixtures/manifest_vector.json";
import { PERMISSIONS, can, decodeToken, secondsLeft } from "../src/lib/auth";
import { canonicalJson } from "../src/lib/canonical";
import { fromHex, sha256Hex, verifyEd25519 } from "../src/lib/crypto";
import { parseMetrics } from "../src/lib/metrics";
import { fmtBytes, fmtCountdown, relTime, shortHash } from "../src/lib/utils";
import { makeToken } from "./helpers";

describe("cross-language contract with the Python service", () => {
  it("canonical JSON is byte-identical to the service's", () => {
    expect(canonicalJson(vector.manifest)).toBe(vector.canonical);
  });
  it("verifies an Ed25519 signature produced by the service-side code", async () => {
    const msg = new TextEncoder().encode(vector.canonical) as Uint8Array<ArrayBuffer>;
    const res = await verifyEd25519(vector.public_key_hex, vector.signature, msg);
    expect(res).toBe("valid");
    const tampered = new TextEncoder().encode(vector.canonical.replace("cam-1", "cam-2")) as Uint8Array<ArrayBuffer>;
    expect(await verifyEd25519(vector.public_key_hex, vector.signature, tampered)).toBe("invalid");
  });
  it("escapes non-ASCII like Python ensure_ascii", () => {
    expect(canonicalJson({ b: "é✓", a: 1 })).toBe('{"a":1,"b":"\\u00e9\\u2713"}');
  });
  it("hashes like SHA-256", async () => {
    expect(await sha256Hex(fromHex("616263"))).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("auth", () => {
  it("decodes a valid token and rejects garbage", () => {
    expect(decodeToken(makeToken())?.role).toBe("auditor");
    for (const bad of ["", "abc", "!!!.x", makeToken({ role: "root" }), `${btoa("{}")}.x`]) expect(decodeToken(bad)).toBeNull();
  });
  it("mirrors least privilege", () => {
    expect(can("admin", "evidence:download")).toBe(false);
    expect(can("auditor", "evidence:download")).toBe(false);
    expect(can("custodian", "evidence:download")).toBe(true);
    expect(can(undefined, "alerts:read")).toBe(false);
    expect(Object.keys(PERMISSIONS)).toHaveLength(6);
  });
  it("computes remaining session time", () => {
    const id = decodeToken(makeToken({ exp: 1000 }))!;
    expect(secondsLeft(id, 400_000)).toBe(600);
  });
});

describe("helpers", () => {
  it("parses Prometheus text and sums labels", () => {
    const m = parseMetrics('# HELP x\ncustody_chunks_total{result="stored"} 3\ncustody_chunks_total{result="rejected"} 1\ncustody_open_alerts 2.0\nbad line\ngauge NaN');
    expect(m.custody_chunks_total).toBe(4);
    expect(m.custody_open_alerts).toBe(2);
    expect(m.gauge).toBeUndefined();
  });
  it("formats", () => {
    expect(fmtBytes(1536)).toBe("1.5 KB");
    expect(shortHash("a".repeat(64))).toContain("…");
    expect(fmtCountdown(75)).toBe("1:15");
    expect(fmtCountdown(0)).toBe("expired");
    expect(relTime(0, 90_000)).toBe("1m ago");
  });
});
