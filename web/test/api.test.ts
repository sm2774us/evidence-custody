import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../src/lib/api";
import { useSession } from "../src/store/session";
import { jsonResponse, makeToken } from "./helpers";

const fetchMock = vi.fn();
beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); useSession.getState().signIn(makeToken()); });
afterEach(() => { vi.unstubAllGlobals(); useSession.getState().signOut(); });

describe("api client", () => {
  it("sends the bearer token and never cookies", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ alerts: [] }));
    await api.alerts("open");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/v1/alerts?status=open");
    expect(init.headers.authorization).toMatch(/^Bearer /);
    expect(init.credentials).toBe("omit");
  });
  it("maps service errors, keeps the request id, and marks 4xx non-retryable", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "forbidden", message: "missing permission x" }, 403, { "x-request-id": "rid-1" }));
    const e = await api.alerts("open").catch((x: unknown) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 403, code: "forbidden", requestId: "rid-1", retryable: false });
  });
  it("marks network failure and 5xx as retryable", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    expect(await api.alerts("open").catch((x: unknown) => x)).toMatchObject({ status: 0, code: "network", retryable: true });
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "boom", message: "x" }, 502));
    expect(await api.alerts("open").catch((x: unknown) => x)).toMatchObject({ status: 502, retryable: true });
  });
  it("signs the user out on 401", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ error: "unauthenticated", message: "token expired" }, 401));
    await api.alerts("open").catch(() => undefined);
    expect(useSession.getState().token).toBeNull();
    expect(useSession.getState().notice).toMatch(/no longer valid/);
  });
  it("surfaces a broken audit chain from /readyz 503 instead of hiding it", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ready: false, audit_entries: 7, audit_error: "hash mismatch at seq 2" }, 503));
    expect(await api.ready()).toEqual({ ready: false, audit_entries: 7, audit_error: "hash mismatch at seq 2" });
  });
  it("times out instead of hanging", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation((_u: unknown, init: RequestInit) => new Promise((_r, rej) => init.signal?.addEventListener("abort", () => rej(new DOMException("aborted", "AbortError")))));
    const p = api.ready().catch((x: unknown) => x);
    await vi.advanceTimersByTimeAsync(6100);
    expect(await p).toMatchObject({ code: "timeout", status: 0 });
    vi.useRealTimers();
  });
  it("sends the access reason header for evidence content", async () => {
    fetchMock.mockResolvedValue(new Response("abc", { headers: { "x-content-sha256": "h" } }));
    const r = await api.content("ev_0123456789abcdef0123", "case review 42");
    expect(fetchMock.mock.calls[0]![1].headers["x-access-reason"]).toBe("case review 42");
    expect(r.headerSha256).toBe("h");
  });
});
