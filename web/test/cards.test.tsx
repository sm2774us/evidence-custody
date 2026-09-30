import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tanstack/react-router", () => ({ Link: ({ children }: { children: React.ReactNode }) => <a href="#x">{children}</a> }));
import { CardView } from "../src/components/cards/CardView";

describe("chat cards", () => {
  it("renders a broken chain as a failure, not a success", () => {
    render(<CardView card={{ kind: "chain", result: { ok: false, entries: 9, head_hash: "a".repeat(64), checkpoints_verified: 0, error: "hash mismatch at seq 2" } }} />);
    expect(screen.getByText(/audit chain broken/i)).toBeInTheDocument();
    expect(screen.getByText(/hash mismatch at seq 2/)).toBeInTheDocument();
  });
  it("labels an unverifiable signature honestly", () => {
    render(<CardView card={{ kind: "custody", signature: "unsupported", view: { key_id: "k", signature: "s", report: { evidence_id: "ev_1", generated_at_ms: 1, sha256_recorded: "a", sha256_now: "a", fixity_ok: true, receipt: {}, derivatives: [], legal_holds: [], custody_events: [], audit_chain: { ok: true, entries: 1, head_hash: "h", checkpoints_verified: 0 } } } }} />);
    expect(screen.getByText(/unchecked \(browser\)/i)).toBeInTheDocument();
  });
});
