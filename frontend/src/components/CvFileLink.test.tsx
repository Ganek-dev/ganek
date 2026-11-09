import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CvFileLink } from "./CvFileLink";

const BASE = {
  id: "app-1",
  cv_filename: "jane.pdf",
  cv_size: 2048,
  cv_scan_status: null,
  cv_scan_signature: null,
} as const;

describe("CvFileLink", () => {
  it("renders the plain download when the CV was never scanned", async () => {
    const onDownload = vi.fn();
    render(<CvFileLink app={BASE} onDownload={onDownload} />);
    await userEvent.click(screen.getByRole("button", { name: /jane\.pdf \(2 KB\)/ }));
    expect(onDownload).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/virus/i)).not.toBeInTheDocument();
  });

  it("shows No CV when there is no file", () => {
    render(
      <CvFileLink app={{ ...BASE, cv_filename: null, cv_size: null }} onDownload={vi.fn()} />,
    );
    expect(screen.getByText("No CV")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("disables the download of an infected CV and explains why", async () => {
    const onDownload = vi.fn();
    render(
      <CvFileLink
        app={{ ...BASE, cv_scan_status: "infected", cv_scan_signature: "Eicar-Test-Signature" }}
        onDownload={onDownload}
      />,
    );
    const button = screen.getByRole("button", { name: /jane\.pdf/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAccessibleDescription(
      /virus scanner flagged this CV \(Eicar-Test-Signature\)\. Ask the candidate to upload a new file\./,
    );
    await userEvent.click(button);
    expect(onDownload).not.toHaveBeenCalled();
  });

  it("keeps the download while the scan is pending and says it is scanning", async () => {
    const onDownload = vi.fn();
    render(<CvFileLink app={{ ...BASE, cv_scan_status: "pending" }} onDownload={onDownload} />);
    expect(screen.getByText("Scanning for viruses")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /jane\.pdf/ }));
    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it("keeps the download after a scanner error and flags it", () => {
    render(<CvFileLink app={{ ...BASE, cv_scan_status: "error" }} onDownload={vi.fn()} />);
    expect(screen.getByText("Not scanned (scanner error)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /jane\.pdf/ })).toBeEnabled();
  });

  it("marks a clean scan", () => {
    render(<CvFileLink app={{ ...BASE, cv_scan_status: "clean" }} onDownload={vi.fn()} />);
    expect(screen.getByText("Virus scan: clean")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /jane\.pdf/ })).toBeEnabled();
  });
});
