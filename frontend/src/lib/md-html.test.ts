import { describe, expect, it } from "vitest";

import { mdToHtml } from "./md-html";

describe("mdToHtml", () => {
  it("converts markdown structure to HTML", () => {
    const html = mdToHtml("# Role\n\nBuild **things**.\n\n- one\n- two");
    expect(html).toContain("<h1>Role</h1>");
    expect(html).toContain("<strong>things</strong>");
    expect(html).toContain("<li>one</li>");
  });

  it("replaces images with their alt text (G4 — no tracking pixels)", () => {
    const html = mdToHtml("Before ![our office](https://tracker.example/p.png) after");
    expect(html).not.toContain("<img");
    expect(html).toContain("our office");
  });

  it("drops alt-less images entirely", () => {
    expect(mdToHtml("![](https://tracker.example/p.png)")).not.toContain("tracker.example");
  });

  it("drops raw HTML instead of passing it through", () => {
    const html = mdToHtml('Hello <script>alert(1)</script> world');
    expect(html).not.toContain("<script>");
  });
});
