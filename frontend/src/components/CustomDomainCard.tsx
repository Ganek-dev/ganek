"use client";

import { useEffect, useState } from "react";

import { Check, Clock } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import { companyApi, type CustomDomainOut } from "@/lib/api";

/** "Custom domain" card on Settings > Branding (board card "Custom domains
 * + subdomain routing", slice 3): claim a careers domain, publish the TXT
 * record shown here, verify. Only a verified domain will ever route. The
 * card stays out of the way where the plan has no custom domains and no
 * upgrade exists (self-hosted: you already serve on your own domain); a
 * domain kept after a downgrade can still be removed.
 *
 * DNS pain points it answers: the exact record with copy buttons, a note
 * for DNS panels that append the zone to the host field, and the server's
 * own reason when the record is not visible yet instead of a silent
 * "pending" that never moves. */

const labelCls = "text-[13.5px] font-semibold";
const hintCls = "text-[12.5px] leading-[18px] text-g500";
const btnCls =
  "inline-flex h-8 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50";

function errorText(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export function CustomDomainCard() {
  const [state, setState] = useState<CustomDomainOut | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    companyApi
      .domain()
      .then((data) => {
        if (!cancelled) setState(data);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function run(action: () => Promise<CustomDomainOut>, done: string, fallback: string) {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      setState(await action());
      setNotice(done);
    } catch (err) {
      setError(errorText(err, fallback));
    } finally {
      setBusy(false);
    }
  }

  if (loadFailed) {
    return (
      <div className="card p-4">
        <p className={labelCls}>Custom domain</p>
        <p className={hintCls}>Could not load the custom domain settings.</p>
      </div>
    );
  }
  if (state === null) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading custom domain"
        className="h-20 animate-pulse rounded-lg bg-muted-fill"
      />
    );
  }
  // self-hosted (or any plan without the feature and nothing to sell): hide
  if (!state.available && state.domain === null && state.upgrade_url === null) return null;

  return (
    <div className="card space-y-3 p-4" data-testid="custom-domain-card">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className={labelCls}>Custom domain</p>
          <p className={hintCls}>
            Serve your careers page on your own domain, such as careers.example.com.
          </p>
        </div>
        {state.status === "verified" ? (
          <span className="inline-flex h-6 shrink-0 items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 text-[11.5px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300">
            <Check aria-hidden className="h-3 w-3" />
            verified
          </span>
        ) : state.status === "pending" ? (
          <span className="inline-flex h-6 shrink-0 items-center gap-1 rounded-full border border-amber-200 bg-amber-50 px-2 text-[11.5px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
            <Clock aria-hidden className="h-3 w-3" />
            pending DNS
          </span>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="text-[13px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-[13px] text-emerald-700 dark:text-emerald-400">
          {notice}
        </p>
      ) : null}

      {state.domain === null ? (
        state.available ? (
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              const domain = input.trim();
              if (domain) run(() => companyApi.setDomain(domain), "Domain added", "Failed to add the domain");
            }}
          >
            <input
              type="text"
              aria-label="Custom domain"
              placeholder="careers.example.com"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              spellCheck={false}
              autoCapitalize="none"
              className="h-9 min-w-0 flex-1 rounded-md border border-edge bg-transparent px-3 font-mono text-[13px] outline-none focus:border-g400"
            />
            <button type="submit" disabled={busy || input.trim() === ""} className={btnCls}>
              {busy ? "…" : "Add domain"}
            </button>
          </form>
        ) : (
          <p className="text-[13px] text-g700">
            Custom domains are part of the Team plan.{" "}
            {state.upgrade_url ? (
              <a href={state.upgrade_url} className="font-medium text-accent underline">
                Upgrade plan
              </a>
            ) : null}
          </p>
        )
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <p className="min-w-0 flex-1 truncate font-mono text-[13px] text-g700">{state.domain}</p>
            {state.status === "pending" && state.available ? (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  run(companyApi.verifyDomain, "Domain verified", "Failed to verify the domain")
                }
                className={btnCls}
              >
                {busy ? "…" : "Verify"}
              </button>
            ) : null}
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setInput("");
                run(companyApi.removeDomain, "Domain removed", "Failed to remove the domain");
              }}
              className="inline-flex h-8 items-center rounded-md px-2 text-[13px] font-medium text-red-600 hover:bg-muted-fill disabled:opacity-50 dark:text-red-400"
            >
              Remove
            </button>
          </div>

          {state.status === "pending" && state.txt_name && state.txt_value ? (
            <div className="space-y-2 rounded-md border border-edge bg-muted-fill p-3">
              <p className="text-[12.5px] leading-[18px] text-g700">
                Add this TXT record at your DNS provider, then press Verify. DNS changes can take
                up to an hour to show.
              </p>
              <DnsRow label="Type" value="TXT" />
              <DnsRow label="Name" value={state.txt_name} copy />
              <DnsRow label="Value" value={state.txt_value} copy />
              <p className={hintCls}>
                If your DNS provider adds your domain to the name by itself, enter only the part
                before it.
              </p>
            </div>
          ) : null}

          {state.status === "verified" ? (
            <p className={hintCls}>
              Ownership confirmed. No other workspace can claim this domain.
            </p>
          ) : null}
          {!state.available ? (
            <p className={hintCls}>
              Your plan no longer includes custom domains, so this domain does not route.
              {state.upgrade_url ? (
                <>
                  {" "}
                  <a href={state.upgrade_url} className="font-medium text-accent underline">
                    Upgrade plan
                  </a>
                </>
              ) : null}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function DnsRow({ label, value, copy = false }: { label: string; value: string; copy?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-12 shrink-0 text-[12px] text-g500">{label}</span>
      <code className="min-w-0 flex-1 break-all font-mono text-[12.5px] text-g700">{value}</code>
      {copy ? <CopyButton text={value} label={`Copy TXT ${label.toLowerCase()}`} /> : null}
    </div>
  );
}
