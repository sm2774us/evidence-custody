import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/lib/api";
import { useChat } from "../src/store/chat";
import { applyTheme, usePrefs, useSession } from "../src/store/session";
import { jsonResponse, makeToken } from "./helpers";

beforeEach(() => { useChat.getState().reset(); useSession.getState().signOut(); usePrefs.setState({ theme: "dark", recents: [] }); });

describe("session store", () => {
  it("rejects malformed and expired tokens; accepts valid ones", () => {
    expect(() => useSession.getState().signIn("garbage")).toThrow(/valid access token/);
    expect(() => useSession.getState().signIn(makeToken({ exp: 10 }))).toThrow(/expired/);
    expect(useSession.getState().signIn(` ${makeToken({ role: "legal" })} `).role).toBe("legal");
    expect(useSession.getState().token).not.toContain(" ");
  });
  it("keeps the token in sessionStorage only, and wipes chat on sign-out", () => {
    useSession.getState().signIn(makeToken());
    expect(sessionStorage.getItem("console-session")).toContain("token");
    expect(localStorage.getItem("console-session")).toBeNull();
    useChat.getState().add({ role: "user", text: "hi" });
    useSession.getState().signOut("bye");
    expect(useSession.getState().notice).toBe("bye");
    expect(sessionStorage.getItem("console-chat")).toBeNull();
  });
});

describe("chat store", () => {
  it("adds, patches and caps history", () => {
    const id = useChat.getState().add({ role: "assistant", pending: true });
    useChat.getState().patch(id, { pending: false, card: { kind: "text", text: "ok" } });
    expect(useChat.getState().messages[0]).toMatchObject({ pending: false, card: { kind: "text" } });
    for (let i = 0; i < 60; i++) useChat.getState().add({ role: "user", text: String(i) });
    expect(useChat.getState().messages).toHaveLength(40);
  });
  it("does not persist in-flight messages", () => {
    useChat.getState().add({ role: "assistant", pending: true });
    useChat.getState().add({ role: "user", text: "kept" });
    const stored = JSON.parse(sessionStorage.getItem("console-chat")!) as { state: { messages: unknown[] } };
    expect(stored.state.messages).toHaveLength(1);
  });
});

describe("prefs", () => {
  it("dedupes and bounds recents; clear empties", () => {
    for (let i = 0; i < 20; i++) usePrefs.getState().remember(`ev_${i}`);
    usePrefs.getState().remember("ev_5");
    expect(usePrefs.getState().recents[0]).toBe("ev_5");
    expect(usePrefs.getState().recents).toHaveLength(12);
    usePrefs.getState().clear();
    expect(usePrefs.getState().recents).toEqual([]);
  });
  it("applies themes, honouring the system preference", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({ matches: q.includes("dark"), addEventListener() {}, removeEventListener() {} }));
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    applyTheme("system");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    vi.unstubAllGlobals();
  });
});

describe("mutating api calls", () => {
  it("send the expected requests", async () => {
    const f = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse({ ok: true })));
    vi.stubGlobal("fetch", f);
    useSession.getState().signIn(makeToken({ role: "custodian" }));
    await api.disposition("up_1", "retry_authorized", "device reflashed");
    await api.requestHold("ev_1", "CASE-1", "pending litigation");
    await api.releaseHold("lh_1", "done");
    await api.registerDevice({ device_id: "cam-1", public_key: "a".repeat(64), officer_id: "o", agency_id: "a" });
    await api.derivative("ev_1", "clip", new File(["x"], "c.mp4", { type: "video/mp4" }), { a: 1 });
    const calls = f.mock.calls.map(([u, i]) => `${(i as RequestInit).method} ${new URL(String(u)).pathname}`);
    expect(calls).toEqual(["POST /v1/quarantine/up_1/disposition", "POST /v1/evidence/ev_1/holds", "POST /v1/holds/lh_1/release", "POST /v1/devices", "POST /v1/evidence/ev_1/derivatives"]);
    expect(JSON.parse((f.mock.calls[0]![1] as RequestInit).body as string)).toEqual({ decision: "retry_authorized", note: "device reflashed" });
    vi.unstubAllGlobals();
  });
});
