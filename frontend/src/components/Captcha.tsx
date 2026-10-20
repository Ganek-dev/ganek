"use client";

import { useEffect, useRef, useState } from "react";

/** Self-hosted proof-of-work check for public forms (board card A5).
 *
 * Probes `/api/v1/public/challenge`: 404 means the instance has the feature
 * off (every single-company instance, and multi mode until the operator
 * enables it), so nothing renders and candidate pages stay exactly as they
 * were. On 200 the ALTCHA widget (bundled, no third-party request, no
 * cookies) solves the challenge in a Web Worker and hands the payload back
 * through `onChange`; the form sends it as `altcha` with its JSON body.
 */

export const CHALLENGE_PATH = "/api/v1/public/challenge";

type Props = {
  onChange: (payload: string | null) => void;
  /** 422 detail from a rejected submit: shows the inline hint and resets. */
  error?: "captcha-required" | "captcha-invalid" | null;
};

type Status = "probing" | "off" | "ready";

export function isCaptchaError(message: string): Props["error"] {
  return message === "captcha-required" || message === "captcha-invalid" ? message : null;
}

export function Captcha({ onChange, error }: Props) {
  const [status, setStatus] = useState<Status>("probing");
  const [challenge, setChallenge] = useState<string | null>(null);
  const hostRef = useRef<HTMLDivElement>(null);

  // probe on mount; a rejected payload (stale or already used) re-probes
  // for a fresh challenge, which remounts the widget via its key
  useEffect(() => {
    let cancelled = false;
    fetch(CHALLENGE_PATH, { headers: { Accept: "application/json" } })
      .then(async (res) => {
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`challenge ${res.status}`);
        return res.text();
      })
      .then((json) => {
        if (cancelled) return;
        if (json === null) {
          setStatus("off");
          return;
        }
        return import("altcha").then(() => {
          if (cancelled) return;
          setChallenge(json);
          setStatus("ready");
        });
      })
      .catch(() => {
        // the probe failing must never block a form; the server will say
        // captcha-required if it really wants one and we retry then
        if (!cancelled) setStatus("off");
      });
    return () => {
      cancelled = true;
    };
  }, [error]);

  useEffect(() => {
    const host = hostRef.current;
    if (status !== "ready" || host === null) return;
    const widget = host.querySelector("altcha-widget");
    if (widget === null) return;
    const read = () => {
      const input = widget.querySelector<HTMLInputElement>('input[name="altcha"]');
      onChange(input?.value ? input.value : null);
    };
    const onState = (event: Event) => {
      const state = (event as CustomEvent<{ state?: string }>).detail?.state;
      if (state === "verified") read();
      else if (state === "expired" || state === "unverified" || state === "error") onChange(null);
    };
    widget.addEventListener("statechange", onState);
    widget.addEventListener("verified", read);
    return () => {
      widget.removeEventListener("statechange", onState);
      widget.removeEventListener("verified", read);
      onChange(null);
    };
  }, [status, challenge, onChange]);

  if (status !== "ready" || challenge === null) return null;

  return (
    <div ref={hostRef} className="mt-5" data-testid="captcha">
      <altcha-widget
        key={challenge}
        challengejson={challenge}
        name="altcha"
        auto="onload"
        hidefooter=""
        hidelogo=""
        style={{ "--altcha-border-radius": "6px" } as React.CSSProperties}
      />
      {error ? (
        <p role="alert" className="mt-2 text-[12.5px]" style={{ color: "var(--danger)" }}>
          {error === "captcha-required"
            ? "Please wait for the verification to finish, then submit again."
            : "The verification expired - it restarted, please submit again."}
        </p>
      ) : (
        <p className="mt-2 text-[12.5px] leading-[18px] text-g500">
          A quick automated check runs in your browser before sending. It uses no cookies
          and talks to no third party.
        </p>
      )}
    </div>
  );
}
