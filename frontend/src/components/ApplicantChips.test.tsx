import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ScreeningAnswer } from "@/lib/api";

import { ScreeningChip } from "./ApplicantChips";

function answer(match: boolean | null): ScreeningAnswer {
  return {
    question_id: "sq_0000aa01",
    type: "yes_no",
    prompt: "Permit?",
    options: null,
    preferred: match === null ? null : "yes",
    answer: match === false ? "no" : "yes",
    match,
  };
}

describe("ScreeningChip", () => {
  it("counts the missed preferred answers", () => {
    render(<ScreeningChip answers={[answer(false), answer(null), answer(false), answer(true)]} />);
    expect(screen.getByText("2 mismatches")).toBeInTheDocument();
  });

  it("singularizes one", () => {
    render(<ScreeningChip answers={[answer(false)]} />);
    expect(screen.getByText("1 mismatch")).toBeInTheDocument();
  });

  it("renders nothing when every preferred answer matched or none was set", () => {
    const { container } = render(<ScreeningChip answers={[answer(true), answer(null)]} />);
    expect(container).toBeEmptyDOMElement();
    const empty = render(<ScreeningChip answers={[]} />);
    expect(empty.container).toBeEmptyDOMElement();
  });
});
