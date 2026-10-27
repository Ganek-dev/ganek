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

  it("flags a custom name that is a built-in source and still offers its link", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    const input = screen.getByLabelText("Custom link name");
    await user.type(input, "google");
    expect(
      screen.getByText("already a built-in source, appears as google in Sources"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy custom link" })).toBeInTheDocument();
    expect(screen.getByText("?src=google")).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "false");
    await user.clear(input);
    await user.type(input, "google_jobs"); // utm alias of the google bucket
    expect(
      screen.getByText("already a built-in source, appears as google in Sources"),
    ).toBeInTheDocument();
  });

  it("withholds the link for direct: it could not be told apart from untracked traffic", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    const input = screen.getByLabelText("Custom link name");
    await user.type(input, "direct");
    expect(screen.getByText(/^direct is the built-in name for untracked traffic/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy custom link" })).not.toBeInTheDocument();
    expect(screen.queryByText("?src=direct")).not.toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("refuses a name the page would drop, with the rule", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    await user.type(screen.getByLabelText("Custom link name"), "Q4 push");
    expect(screen.getByText("letters, digits, - or _ only, up to 40")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Copy custom link" })).not.toBeInTheDocument();
  });

  it("labels the custom input with one visible label and describes it by its status line", async () => {
    const user = userEvent.setup();
    render(<ShareLinksCard jobUrl={JOB_URL} live />);
    const input = screen.getByLabelText("Custom link name");
    expect(screen.getByText("Custom link name").tagName).toBe("LABEL");
    expect(input).not.toHaveAttribute("aria-label");
    expect(input).toHaveAttribute("aria-invalid", "false");
    const status = document.getElementById(input.getAttribute("aria-describedby")!.split(" ")[0])!;
    expect(status).toHaveAttribute("aria-live", "polite");
    await user.type(input, "Q4 push");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(status).toHaveTextContent("letters, digits, - or _ only, up to 40");
    await user.clear(input);
    await user.type(input, "q4-push");
    expect(input).toHaveAttribute("aria-invalid", "false");
    expect(status).toHaveTextContent("appears as link:q4-push in Sources");
    expect(input.getAttribute("aria-describedby")!.split(" ")).toContain(
      screen.getByText("?src=q4-push").closest("ul")!.id,
    );
  });

  it("says why there are no links when the company could not be loaded", () => {
    render(<ShareLinksCard jobUrl={null} live urlFailed />);
    expect(screen.getByText("Share links load with the company.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Loading share links")).not.toBeInTheDocument();
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
    expect(container.textContent).not.toMatch(/[\u2013\u2014]/);
  });
});
