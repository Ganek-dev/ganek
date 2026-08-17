import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { CopyButton } from "./CopyButton";

describe("CopyButton", () => {
  it("copies the text and confirms, then reverts", async () => {
    const user = userEvent.setup();
    render(<CopyButton text="https://jobs.example.com" label="Copy careers URL" />);

    await user.click(screen.getByRole("button", { name: "Copy careers URL" }));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
    expect(await window.navigator.clipboard.readText()).toBe("https://jobs.example.com");
  });

  it("renders custom idle content", () => {
    render(<CopyButton text="x" label="Copy id">Copy ID</CopyButton>);
    expect(screen.getByText("Copy ID")).toBeInTheDocument();
  });
});
