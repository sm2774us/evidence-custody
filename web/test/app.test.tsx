import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildRouter } from "../src/router";
import { useSession } from "../src/store/session";
import { jsonResponse, makeToken } from "./helpers";

const fetchMock = vi.fn();
function routes(url: string): Response {
  if (url.includes("/readyz")) return jsonResponse({ ready: true, audit_entries: 12, audit_error: null });
  if (url.includes("/metrics")) return new Response("custody_evidence_stored_total 5\ncustody_open_alerts 1\n");
  if (url.includes("/v1/alerts")) return jsonResponse({ alerts: [{ alert_id: "al_1", ts_ms: Date.now(), kind: "HASH_MISMATCH", severity: "high", object_id: "up_1", status: "open", acked_by: null, acked_at_ms: null, detail: { advisory: { summary: "Every chunk matched but the object did not." } } }] });
  return jsonResponse({ error: "not_found", message: "nope" }, 404);
}
beforeEach(() => { vi.stubGlobal("fetch", vi.fn((u: URL | string) => Promise.resolve(fetchMock(String(u)) ?? routes(String(u))))); fetchMock.mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); useSession.getState().signOut(); });

function mount(path = "/") {
  const router = buildRouter(createMemoryHistory({ initialEntries: [path] }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><RouterProvider router={router} /></QueryClientProvider>);
}

describe("app shell", () => {
  it("redirects anonymous users to sign-in, rejects a bad token, then reaches the dashboard", async () => {
    fetchMock.mockImplementation(routes);
    mount();
    expect(await screen.findByRole("heading", { name: /evidence console/i })).toBeInTheDocument();
    const user = userEvent.setup();
    const box = screen.getByLabelText(/access token/i);
    await user.type(box, "not-a-token");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/valid access token/i);

    await user.clear(box);
    await user.click(box);
    await user.paste(makeToken({ role: "auditor" }));
    expect(await screen.findByText(/audit-1|aud-1/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("heading", { name: /operations dashboard/i })).toBeInTheDocument();
    expect(await screen.findByText("HASH_MISMATCH")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary" })).toHaveTextContent(/Audit log/);
  });

  it("shows only what the role may use (least privilege in the navigation)", async () => {
    fetchMock.mockImplementation(routes);
    useSession.getState().signIn(makeToken({ role: "reader", sub: "rdr-1" }));
    mount();
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(nav).toHaveTextContent(/Evidence/);
    expect(nav).not.toHaveTextContent(/Audit log|Alerts|Uploads/);
  });

  it("flags an audit integrity failure prominently", async () => {
    fetchMock.mockImplementation((u: string) => (u.includes("/readyz") ? jsonResponse({ ready: false, audit_entries: 3, audit_error: "hash mismatch at seq 2" }, 503) : routes(u)));
    useSession.getState().signIn(makeToken({ role: "reader" }));
    mount();
    await waitFor(() => expect(screen.getAllByText(/audit integrity failure/i).length).toBeGreaterThan(0));
  });
});

