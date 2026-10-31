import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ScreeningAnswer } from "@/lib/api";

import { ScreeningAnswers } from "./ScreeningAnswers";

const ANSWERS: ScreeningAnswer[] = [
  {
    question_id: "sq_0000aa01",
    type: "yes_no",
    prompt: "Can you work in Germany?",
    options: null,
    preferred: "yes",
    answer: "no",
    match: false,
  },
  {
    question_id: "sq_0000aa02",
    type: "single_choice",
    prompt: "Days on site?",
    options: ["0", "1-2", "3+"],
    preferred: "1-2",
    answer: "1-2",
    match: true,
  },
  {
    question_id: "sq_0000aa03",
    type: "short_text",
    prompt: "Notice period?",
    options: null,
    preferred: null,
    answer: null,
    match: null,
  },
  {
    question_id: "sq_0000aa04",
    type: "acknowledgment",
    prompt: "I confirm the information is accurate",
    options: null,
    preferred: null,
    answer: true,
    match: null,
  },
];

describe("ScreeningAnswers", () => {
  it("renders nothing for an applicant without answers", () => {
    const { container } = render(<ScreeningAnswers answers={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists every question with its answer and marks the mismatch with the preferred answer", () => {
    render(<ScreeningAnswers answers={ANSWERS} />);
    expect(screen.getByText("Screening answers")).toBeInTheDocument();
    const permit = screen.getByText("Can you work in Germany?").closest("li")!;
    expect(permit).toHaveTextContent("No");
    expect(permit).toHaveTextContent("Preferred: Yes");
    const days = screen.getByText("Days on site?").closest("li")!;
    expect(days).toHaveTextContent("1-2");
    expect(days).not.toHaveTextContent("Preferred");
    expect(screen.getByText("Notice period?").closest("li")).toHaveTextContent("Not answered");
    expect(
      screen.getByText("I confirm the information is accurate").closest("li"),
    ).toHaveTextContent("Accepted");
  });

  it("states the match in text, not only in the icon", () => {
    render(<ScreeningAnswers answers={ANSWERS} />);
    expect(screen.getByText("Mismatch")).toBeInTheDocument();
    expect(screen.getByText("Matches the preferred answer")).toBeInTheDocument();
  });
});
