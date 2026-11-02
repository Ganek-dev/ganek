import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BoardStatus } from "@/lib/api";

import { StatusChip } from "./StatusChip";

const CASES: [BoardStatus, string, string][] = [
  ["stalled", "Stalled", "danger"],
  ["attention", "Needs attention", "warn"],
  ["on_track", "On track", "ok"],
  ["empty", "Empty", "g600"],
];

describe("StatusChip", () => {
  it.each(CASES)(
    "renders %s with label, semantic class and reason as title",
    (status, label, tone) => {
      render(<StatusChip status={status} reason="Because of a rule." />);
      const chip = screen.getByText(label).closest("span[title]");
      expect(chip).not.toBeNull();
      expect(chip).toHaveAttribute("title", "Because of a rule.");
      expect(chip?.className).toContain(tone);
    },
  );
});
