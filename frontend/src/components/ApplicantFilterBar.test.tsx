import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_FILTERS, type ApplicantFilters } from "@/lib/applicant-filters";

import { ApplicantFilterBar } from "./ApplicantFilterBar";

const SOURCES = ["direct", "github", "linkedin"];

function setup(filters: Partial<ApplicantFilters> = {}) {
  const onChange = vi.fn();
  render(
    <ApplicantFilterBar
      filters={{ ...DEFAULT_FILTERS, ...filters }}
      sources={SOURCES}
      onChange={onChange}
    />,
  );
  return { onChange };
}

describe("ApplicantFilterBar", () => {
  it("renders every control with a label", () => {
    setup();
    expect(screen.getByLabelText("Search applicants")).toHaveAttribute(
      "placeholder",
      "Search name or email…",
    );
    for (const label of ["Score", "Quiz", "Source", "Flags", "Screening", "Applied"]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Clear filters" })).not.toBeInTheDocument();
  });

  it("debounces the search and reports the text once", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.type(screen.getByLabelText("Search applicants"), "erika");
    expect(onChange).not.toHaveBeenCalled(); // nothing per keystroke
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(onChange).toHaveBeenCalledWith({ q: "erika" });
  });

  it("each select reports its typed value", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.selectOptions(screen.getByLabelText("Score"), "60");
    expect(onChange).toHaveBeenLastCalledWith({ score: 60 });
    await user.selectOptions(screen.getByLabelText("Quiz"), "pending");
    expect(onChange).toHaveBeenLastCalledWith({ quiz: "pending" });
    await user.selectOptions(screen.getByLabelText("Source"), "linkedin");
    expect(onChange).toHaveBeenLastCalledWith({ source: "linkedin" });
    await user.selectOptions(screen.getByLabelText("Flags"), "true");
    expect(onChange).toHaveBeenLastCalledWith({ flagged: true });
    await user.selectOptions(screen.getByLabelText("Flags"), "false");
    expect(onChange).toHaveBeenLastCalledWith({ flagged: false });
    await user.selectOptions(screen.getByLabelText("Applied"), "30");
    expect(onChange).toHaveBeenLastCalledWith({ days: 30 });
    await user.selectOptions(screen.getByLabelText("Screening"), "mismatch");
    expect(onChange).toHaveBeenLastCalledWith({ screening: "mismatch" });
    await user.selectOptions(screen.getByLabelText("Screening"), "");
    expect(onChange).toHaveBeenLastCalledWith({ screening: null });
  });

  it("resets a select to null on its 'Any' option", async () => {
    const user = userEvent.setup();
    const { onChange } = setup({ score: 60, quiz: "completed" });
    expect(screen.getByLabelText("Score")).toHaveValue("60");
    await user.selectOptions(screen.getByLabelText("Score"), "");
    expect(onChange).toHaveBeenLastCalledWith({ score: null });
  });

  it("lists the sources it is given, with direct spelled out", () => {
    setup();
    const options = Array.from(
      (screen.getByLabelText("Source") as HTMLSelectElement).options,
      (option) => option.textContent,
    );
    expect(options).toEqual(["Any source", "Direct", "github", "linkedin"]);
  });

  it("offers Clear filters only when something narrows, and clears all of it", async () => {
    const user = userEvent.setup();
    const { onChange } = setup({ q: "ben", flagged: false, job: "job-1", sort: "name_asc" });
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(onChange).toHaveBeenCalledWith({
      q: "",
      score: null,
      quiz: null,
      source: null,
      flagged: null,
      days: null,
      screening: null,
      waiting: null,
    });
  });

  it("toggles the waiting chips, mutually exclusive, and a second click clears", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    const team = screen.getByRole("button", { name: "Waiting on you" });
    const candidate = screen.getByRole("button", { name: "Waiting on candidate" });
    expect(team).toHaveAttribute("aria-pressed", "false");
    await user.click(team);
    expect(onChange).toHaveBeenLastCalledWith({ waiting: "team" });
    await user.click(candidate);
    expect(onChange).toHaveBeenLastCalledWith({ waiting: "candidate" });
  });

  it("shows the active chip pressed and clears it on a second click", async () => {
    const user = userEvent.setup();
    const { onChange } = setup({ waiting: "team" });
    const team = screen.getByRole("button", { name: "Waiting on you" });
    expect(team).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Waiting on candidate" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeInTheDocument();
    await user.click(team);
    expect(onChange).toHaveBeenLastCalledWith({ waiting: null });
  });

  it("shows the current search text and keeps typing local until the debounce fires", async () => {
    const user = userEvent.setup();
    const { onChange } = setup({ q: "ben" });
    const input = screen.getByLabelText("Search applicants");
    expect(input).toHaveValue("ben");
    await user.clear(input);
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith({ q: "" }));
  });
});
