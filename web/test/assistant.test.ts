import { afterEach, describe, expect, it, vi } from "vitest";
import { parseIntent } from "../src/assistant/intents";
import { execute } from "../src/assistant/run";
import { ApiError, api } from "../src/lib/api";

const EV = "ev_0123456789abcdef0123";
const UP = "up_0123456789abcdef0123";
const AL = "al_0123456789abcdef";

describe("intent parsing", () => {
  it.each([
    ["help", "help"], ["", "help"], ["status", "status"], ["how are we doing", "status"], ["open alerts", "alerts"],
    ["show acknowledged alerts", "alerts"], ["verify audit chain", "verify"], ["scan for anomalies", "scan"], ["sign a checkpoint", "checkpoint"],
    [`evidence ${EV}`, "evidence"], [EV.toUpperCase(), "evidence"], [`custody report for ${EV}`, "custody"], [`why ${UP}`, "triage"],
    [`inspect ${UP}`, "upload"], [`ack ${AL}`, "ack"], ["gaps cam-0001", "gaps"], ["missing sequence for cam-9", "gaps"], ["banana", "unknown"],
  ])("%s -> %s", (input, kind) => expect(parseIntent(input).kind).toBe(kind));

  it("captures ids and status", () => {
    expect(parseIntent(`custody ${EV}`)).toEqual({ kind: "custody", id: EV });
    expect(parseIntent("acknowledged alerts")).toEqual({ kind: "alerts", status: "acknowledged" });
    expect(parseIntent("gaps cam-0001")).toEqual({ kind: "gaps", device: "cam-0001" });
  });
  it("ignores look-alike ids and never treats ids as device names", () => {
    expect(parseIntent("evidence ev_zzzz").kind).toBe("unknown");
    expect(parseIntent(`gaps ${EV}`).kind).toBe("evidence");
  });
});

describe("assistant execution", () => {
  afterEach(() => vi.restoreAllMocks());
  it("refuses locally when the role lacks permission, without calling the API", async () => {
    const spy = vi.spyOn(api, "auditVerify");
    const card = await execute({ kind: "verify" }, "custodian");
    expect(card).toMatchObject({ kind: "error", status: 403 });
    expect(spy).not.toHaveBeenCalled();
  });
  it("returns data cards on success", async () => {
    vi.spyOn(api, "alerts").mockResolvedValue([]);
    expect(await execute({ kind: "alerts", status: "open" }, "auditor")).toMatchObject({ kind: "alerts", items: [] });
    vi.spyOn(api, "gaps").mockResolvedValue([1, 4]);
    expect(await execute({ kind: "gaps", device: "cam-1" }, "reader")).toMatchObject({ kind: "gaps", missing: [1, 4] });
  });
  it("converts API failures into an error card with the request id", async () => {
    vi.spyOn(api, "evidence").mockRejectedValue(new ApiError(404, "not_found", "evidence not found", "rid-9"));
    expect(await execute({ kind: "evidence", id: EV }, "reader")).toEqual({ kind: "error", message: "evidence not found", status: 404, requestId: "rid-9" });
    vi.spyOn(api, "triage").mockRejectedValue(new Error("kaboom"));
    expect(await execute({ kind: "triage", id: UP }, "custodian")).toMatchObject({ kind: "error", message: "kaboom" });
  });
  it("status tolerates a missing metrics endpoint", async () => {
    vi.spyOn(api, "ready").mockResolvedValue({ ready: true, audit_entries: 3, audit_error: null });
    vi.spyOn(api, "metricsText").mockRejectedValue(new Error("nope"));
    expect(await execute({ kind: "status" }, "reader")).toMatchObject({ kind: "status", metrics: {} });
  });
});
