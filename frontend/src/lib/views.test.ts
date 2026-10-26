import { describe, expect, it } from "vitest";

import { isBotUserAgent, isPrefetch, shouldCountView, viewHeaders } from "./views";

const CHROME =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36";
const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";
const FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0";

function headersOf(entries: Record<string, string>) {
  const lower = Object.fromEntries(
    Object.entries(entries).map(([key, value]) => [key.toLowerCase(), value]),
  );
  return { get: (name: string) => lower[name.toLowerCase()] ?? null };
}

const clean = { userAgent: CHROME, hasSession: false, preview: undefined, prefetch: false };

describe("isBotUserAgent", () => {
  it.each([
    ["Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"],
    ["Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"],
    ["Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)"],
    ["facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"],
    ["Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/120.0.0.0 Safari/537.36"],
    ["Mozilla/5.0 (Macintosh) Chrome/120 Chrome-Lighthouse"],
    ["Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)"],
    ["LinkedInBot/1.0 (compatible; Mozilla/5.0; Jakarta Commons-HttpClient/3.1 +http://www.linkedin.com)"],
    ["Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)"],
    ["Mozilla/5.0 (compatible; DuckDuckGo-Favicons-Bot/1.0)"],
    ["WhatsApp/2.23 preview"],
  ])("%s is a bot", (ua) => {
    expect(isBotUserAgent(ua)).toBe(true);
  });

  it.each([[CHROME], [IPHONE], [FIREFOX]])("%s is a person", (ua) => {
    expect(isBotUserAgent(ua)).toBe(false);
  });

  it("treats a missing or empty user agent as not a person", () => {
    expect(isBotUserAgent(null)).toBe(true);
    expect(isBotUserAgent("")).toBe(true);
  });
});

describe("isPrefetch", () => {
  it("recognises every prefetch header form", () => {
    expect(isPrefetch(headersOf({ "Next-Router-Prefetch": "1" }))).toBe(true);
    expect(isPrefetch(headersOf({ Purpose: "prefetch" }))).toBe(true);
    expect(isPrefetch(headersOf({ "Sec-Purpose": "prefetch;prerender" }))).toBe(true);
  });

  it("is false for a plain navigation", () => {
    expect(isPrefetch(headersOf({}))).toBe(false);
    expect(isPrefetch(headersOf({ Purpose: "navigate" }))).toBe(false);
  });
});

describe("shouldCountView", () => {
  it("counts a clean candidate load", () => {
    expect(shouldCountView(clean)).toBe(true);
  });

  it("never counts a signed-in recruiter", () => {
    expect(shouldCountView({ ...clean, hasSession: true })).toBe(false);
  });

  it("never counts a preview, whatever the token", () => {
    expect(shouldCountView({ ...clean, preview: "tok" })).toBe(false);
    expect(shouldCountView({ ...clean, preview: "" })).toBe(true); // absent in practice
  });

  it("never counts a router prefetch", () => {
    expect(shouldCountView({ ...clean, prefetch: true })).toBe(false);
  });

  it("never counts a bot", () => {
    expect(shouldCountView({ ...clean, userAgent: "Googlebot/2.1" })).toBe(false);
    expect(shouldCountView({ ...clean, userAgent: null })).toBe(false);
  });
});

describe("viewHeaders", () => {
  it("names the view and its source for the backend", () => {
    expect(viewHeaders("linkedin")).toEqual({ "X-Ganek-View": "1", "X-Ganek-Source": "linkedin" });
    expect(viewHeaders("link:newsletter")["X-Ganek-Source"]).toBe("link:newsletter");
  });
});
