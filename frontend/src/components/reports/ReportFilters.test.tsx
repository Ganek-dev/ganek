import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ReportFilters } from "./ReportFilters";

const jobs = [
  { job_id: "a", title: "Draft role", status: "draft" as const },
  { job_id: "b", title: "Backend", status: "published" as const },
  { job_id: "c", title: "Old role", status: "closed" as const },
];

describe("ReportFilters", () => {
  it("marks the active period", () => {
    render(<ReportFilters period="12m" job={null} jobs={jobs} onChange={vi.fn()} />);
    expect(screen.getByRole("radio", { name: "12 months" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "90 days" })).not.toBeChecked();
  });

  it("reports a period change", async () => {
    const onChange = vi.fn();
    render(<ReportFilters period="90d" job={null} jobs={jobs} onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "All time" }));
    expect(onChange).toHaveBeenCalledWith({ period: "all" });
  });

  it("lists drafts last and reports a job change", async () => {
    const onChange = vi.fn();
    render(<ReportFilters period="90d" job={null} jobs={jobs} onChange={onChange} />);
    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["All jobs", "Backend", "Old role (closed)", "Draft role (draft)"]);
    await userEvent.selectOptions(screen.getByLabelText("Job"), "b");
    expect(onChange).toHaveBeenCalledWith({ job: "b" });
    await userEvent.selectOptions(screen.getByLabelText("Job"), "");
    expect(onChange).toHaveBeenCalledWith({ job: null });
  });
});
