import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CHALLENGE_PATH, Captcha, WIDGET_CONFIGURATION, isCaptchaError } from "./Captcha";

// the widget package registers a custom element on import; jsdom renders
// the <altcha-widget> tag as an unknown element, which is all we need
vi.mock("altcha", () => ({}));

const CHALLENGE = JSON.stringify({
  algorithm: "SHA-256",
  challenge: "abc",
  maxnumber: 1000,
  salt: "s?expires=1&",
  signature: "sig",
});

function stubFetch(status: number, body = CHALLENGE) {
  const fetchMock = vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    text: () => Promise.resolve(body),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("Captcha", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing when the instance has the feature off (404)", async () => {
    const fetchMock = stubFetch(404);
    const onChange = vi.fn();
    const { container } = render(<Captcha onChange={onChange} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(CHALLENGE_PATH, expect.anything()));
    expect(container).toBeEmptyDOMElement();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("renders nothing when the probe fails, so a form is never blocked", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { container } = render(<Captcha onChange={vi.fn()} />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("mounts the widget with the challenge and hands the solved payload up", async () => {
    stubFetch(200);
    const onChange = vi.fn();
    render(<Captcha onChange={onChange} />);
    const widget = await waitFor(() => {
      const el = document.querySelector("altcha-widget");
      expect(el).not.toBeNull();
      return el as HTMLElement;
    });
    // 3.x reads `challenge` + `configuration`; the 2.x attributes
    // (challengejson, hidefooter, hidelogo) are ignored, so a widget that
    // only got those would never solve anything: guard against a regression
    expect(widget.getAttribute("challenge")).toBe(CHALLENGE);
    expect(widget.getAttribute("challengejson")).toBeNull();
    expect(widget.getAttribute("hidefooter")).toBeNull();
    expect(JSON.parse(widget.getAttribute("configuration") ?? "{}")).toEqual({
      hideFooter: true,
      hideLogo: true,
      humanInteractionSignature: false,
    });
    expect(widget.getAttribute("configuration")).toBe(WIDGET_CONFIGURATION);
    expect(widget.getAttribute("name")).toBe("altcha");
    // the widget speaks for itself; no explanatory copy under it (owner, 2026-10-23)
    expect(screen.queryByText(/automated check/)).toBeNull();

    // what the widget does once solved: fills its hidden input, fires events
    const input = document.createElement("input");
    input.name = "altcha";
    input.value = "c29sdmVk";
    widget.appendChild(input);
    act(() => {
      widget.dispatchEvent(new CustomEvent("statechange", { detail: { state: "verified" } }));
    });
    expect(onChange).toHaveBeenLastCalledWith("c29sdmVk");

    act(() => {
      widget.dispatchEvent(new CustomEvent("statechange", { detail: { state: "expired" } }));
    });
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("explains a rejected submit inline and fetches a fresh challenge", async () => {
    const fetchMock = stubFetch(200);
    const { rerender } = render(<Captcha onChange={vi.fn()} error={null} />);
    await waitFor(() => expect(document.querySelector("altcha-widget")).not.toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);

    rerender(<Captcha onChange={vi.fn()} error="captcha-invalid" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/verification expired/);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    rerender(<Captcha onChange={vi.fn()} error="captcha-required" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/wait for the verification/);
  });

  it("recognises only the two stable backend details", () => {
    expect(isCaptchaError("captcha-required")).toBe("captcha-required");
    expect(isCaptchaError("captcha-invalid")).toBe("captcha-invalid");
    expect(isCaptchaError("You already applied for this position")).toBeNull();
  });
});
