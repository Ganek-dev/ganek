import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { reportsFixture } from "./reportsFixture";
import { ScoreDistribution } from "./ScoreDistribution";

describe("ScoreDistribution", () => {
  it("labels the chart and shows the median with n", () => {
    render(<ScoreDistribution quiz={reportsFixture.quiz_scores} />);
    expect(
      screen.getByRole("img", { name: "Score distribution, 97 completed assessments" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/median/)).toHaveTextContent("median 66 (n = 97)");
  });

  it("shows no median below n = 3", () => {
    const dist = Array(10).fill(0);
    dist[6] = 2;
    render(
      <ScoreDistribution
        quiz={{ ...reportsFixture.quiz_scores, attempts_completed: 2, median_score: 0.65, score_distribution: dist }}
      />,
    );
    expect(screen.getByText(/median/)).toHaveTextContent("median - (n = 2)");
  });

  it("draws one colour, no pass line, no pass rate", () => {
    render(<ScoreDistribution quiz={reportsFixture.quiz_scores} />);
    const colours = new Set(
      screen.getAllByTestId("score-bar").map((bar) => (bar as HTMLElement).style.background),
    );
    expect(colours.size).toBe(1);
    expect(screen.queryByText(/pass/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/avg time/i)).not.toBeInTheDocument();
  });

  it("has a table under the chart", () => {
    render(<ScoreDistribution quiz={reportsFixture.quiz_scores} />);
    expect(screen.getByRole("row", { name: "60-69 21" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: "90-100 5" })).toBeInTheDocument();
  });

  it("says so when nothing is completed", () => {
    render(
      <ScoreDistribution
        quiz={{ ...reportsFixture.quiz_scores, attempts_completed: 0, median_score: null, score_distribution: Array(10).fill(0) }}
      />,
    );
    expect(screen.getByText("No completed assessments yet.")).toBeInTheDocument();
  });
});
