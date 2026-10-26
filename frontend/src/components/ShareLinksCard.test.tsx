import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ShareLinksCard } from "./ShareLinksCard";

const JOB_URL = "https://jobs.acme.com/jobs/senior-frontend-engineer";

describe("ShareLinksCard", () => {
  it("lists one ready link per channel and copies it", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    expect(screen.getByText("Share this job")).toBeInTheDocument();
    for (const [label, name] of [
      ["LinkedIn", "linkedin"],
      ["Indeed", "indeed"],
      ["X", "x"],
      ["Newsletter", "newsletter"],
    ]) {
      const row = screen.getByText(label, { exact: true }).closest("li")!;
      // the base may truncate in the 320px rail; the part that differs never does
      expect(within(row).getByText("jobs.acme.com/jobs/senior-frontend-engineer")).toBeInTheDocument();
      expect(within(row).getByText(`?src=${name}`)).toBeInTheDocument();
      expect(within(row).getByTitle(`${JOB_URL}?src=${name}`)).toBeInTheDocument();
      expect(within(row).getByRole("button", { name: `Copy ${label} link` })).toBeInTheDocument();
    }
    await user.click(screen.getByRole("button", { name: "Copy LinkedIn link" }));
    expect(await window.navigator.clipboard.readText()).toBe(`${JOB_URL}?src=linkedin`);
  });

  it("builds a custom link from a typed name and says how it will appear", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    const input = screen.getByLabelText("Custom link name");
    await user.type(input, "Newsletter-Q4");
    expect(screen.getByText("?src=newsletter-q4")).toBeInTheDocument();
    expect(screen.getByText("appears as link:newsletter-q4 in Sources")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy custom link" }));
    expect(await window.navigator.clipboard.readText()).toBe(`${JOB_URL}?src=newsletter-q4`);
  });

  it("maps a custom name that is a known bucket to that bucket", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    await user.type(screen.getByLabelText("Custom link name"), "linkedin");
    expect(screen.getByText("appears as linkedin in Sources")).toBeInTheDocument();
  });

  it("refuses a name the page would drop, with the rule", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    await user.type(screen.getByLabelText("Custom link name"), "Q4 push");
    expect(screen.getByText("letters, digits, - or _ only, up to 40")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy custom link" })).not.toBeInTheDocument();
  });

  it("tells a draft to publish first and offers no input", () => {
    render(<ShareLinksCard jobUrl={null} live={false} />);
    expect(screen.getByText("Publish to get share links.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Custom link name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Copy/ })).not.toBeInTheDocument();
  });

  it("shows a skeleton while the public URL is unknown", () => {
    render(<ShareLinksCard jobUrl={null} live />);
    expect(screen.getByLabelText("Loading share links")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText(/\?src=/)).not.toBeInTheDocument();
    expect(screen.queryByText(/jobs\.acme/)).not.toBeInTheDocument();
  });

  it("links the embed docs and warns against naming links after people", () => {
    const { container } = render(<ShareLinksCard jobUrl={JOB_URL} live />);
    expect(screen.getByRole("link", { name: "How to embed jobs on your site" })).toHaveAttribute(
      "href",
      "https://ganek.dev/api-embed/",
    );
    expect(screen.getByText("Name links after channels, never after a person.")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/[–—]/);
  });
});
