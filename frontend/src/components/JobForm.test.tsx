import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { JobInput } from "@/lib/api";

import { JobForm } from "./JobForm";

describe("JobForm", () => {
  it("renders all fields with defaults", () => {
    render(<JobForm submitLabel="Create job" onSubmit={vi.fn()} />);
    expect(screen.getByLabelText("Title")).toBeRequired();
    expect(screen.getByLabelText("Remote policy")).toHaveValue("onsite");
    expect(screen.getByLabelText("Employment type")).toHaveValue("full_time");
    expect(screen.getByRole("button", { name: "Create job" })).toBeInTheDocument();
  });

  it("submits normalized values", async () => {
    const onSubmit = vi.fn<(values: JobInput) => Promise<void>>().mockResolvedValue();
    render(<JobForm submitLabel="Create job" onSubmit={onSubmit} />);

    await userEvent.type(screen.getByLabelText("Title"), "Senior Python Dev");
    await userEvent.type(screen.getByLabelText(/Tags/), "Python, FastAPI , backend,");
    await userEvent.type(screen.getByLabelText("Salary min"), "15000");
    await userEvent.click(screen.getByRole("button", { name: "Create job" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Senior Python Dev",
        tags: ["python", "fastapi", "backend"],
        salary_min: 15000,
        salary_max: null,
        salary_currency: null,
      }),
    );
  });
});
