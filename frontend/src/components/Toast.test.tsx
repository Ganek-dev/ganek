import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Toast, TOAST_MS } from "./Toast";

describe("Toast", () => {
  it("keeps the live region mounted while empty", () => {
    render(<Toast message={null} onDismiss={() => {}} />);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("announces the text and runs the action", async () => {
    const run = vi.fn().mockResolvedValue(undefined);
    const onDismiss = vi.fn();
    render(
      <Toast
        message={{ id: 1, text: "Moved Jane to Screening.", action: { label: "Undo", run } }}
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Moved Jane to Screening.");
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(run).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  describe("timer", () => {
    beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }));
    afterEach(() => vi.useRealTimers());

    it("dismisses itself after the delay", () => {
      const onDismiss = vi.fn();
      render(<Toast message={{ id: 1, text: "Moved." }} onDismiss={onDismiss} />);
      vi.advanceTimersByTime(TOAST_MS - 1);
      expect(onDismiss).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(onDismiss).toHaveBeenCalledTimes(1);
    });

    it("pauses while the pointer is on it", () => {
      const onDismiss = vi.fn();
      render(<Toast message={{ id: 1, text: "Moved." }} onDismiss={onDismiss} />);
      const box = screen.getByText("Moved.").parentElement as HTMLElement;
      // fireEvent, not user-event: user-event would wait on the fake clock
      fireEvent.mouseEnter(box);
      vi.advanceTimersByTime(TOAST_MS * 2);
      expect(onDismiss).not.toHaveBeenCalled();
      fireEvent.mouseLeave(box);
      vi.advanceTimersByTime(TOAST_MS);
      expect(onDismiss).toHaveBeenCalledTimes(1);
    });
  });
});
