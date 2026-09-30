import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConfirmButton } from "../src/components/ui/misc";

describe("ConfirmButton (two-click safety for mutating actions)", () => {
  it("does not act on the first click, acts on the second", async () => {
    const fn = vi.fn();
    render(<ConfirmButton label="Acknowledge" confirmLabel="Confirm ack" onConfirm={fn} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(fn).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm ack" }));
    expect(fn).toHaveBeenCalledTimes(1);
  });
  it("disarms itself after 5 seconds", async () => {
    vi.useFakeTimers();
    const fn = vi.fn();
    render(<ConfirmButton label="Revoke" onConfirm={fn} />);
    act(() => screen.getByRole("button", { name: "Revoke" }).click());
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(5100); });
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    expect(fn).not.toHaveBeenCalled();
    vi.useRealTimers();
  });
});
