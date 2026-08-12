"use client";

import { useEffect, useState } from "react";

import { ExternalLink } from "lucide-react";

import { SettingsTabs } from "@/components/SettingsTabs";
import { companyApi, type CompanyAdmin } from "@/lib/api";

/** Privacy settings (M5.6 G1): the per-company variables the candidate
 * privacy notice renders — controller identity, rights contact, retention
 * window, optional own-policy link. The notice itself lives on the public
 * careers site; this tab only feeds it. */

const RETENTION_DEFAULT = 6;

const labelCls = "text-[13.5px] font-semibold";
const hintCls = "text-[12.5px] leading-[18px] text-g500";
const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-[13.5px] outline-none focus:border-g400";

export default function PrivacySettingsPage() {
  const [company, setCompany] = useState<CompanyAdmin | null>(null);
  const [legalName, setLegalName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [retention, setRetention] = useState<number | "">("");
  const [policyUrl, setPolicyUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    companyApi
      .get()
      .then((data) => {
        setCompany(data);
        setLegalName(data.settings.legal_name ?? "");
        setContactEmail(data.settings.privacy_contact_email ?? "");
        setRetention(data.settings.retention_months ?? "");
        setPolicyUrl(data.settings.privacy_policy_url ?? "");
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load settings"),
      );
  }, []);

  async function save() {
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const updated = await companyApi.updateSettings({
        legal_name: legalName.trim() === "" ? null : legalName.trim(),
        privacy_contact_email: contactEmail.trim() === "" ? null : contactEmail.trim(),
        retention_months: retention === "" ? null : retention,
        privacy_policy_url: policyUrl.trim() === "" ? null : policyUrl.trim(),
      });
      setCompany(updated);
      setNotice("Privacy settings saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setBusy(false);
    }
  }

  if (company === null) {
    return (
      <section className="max-w-[680px] space-y-4">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
        {error ? (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : (
          <div aria-busy="true" className="space-y-2">
            {Array.from({ length: 3 }, (_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-lg bg-muted-fill" />
            ))}
          </div>
        )}
      </section>
    );
  }

  return (
    <section className="max-w-[680px] space-y-4">
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">Settings</h1>
      <SettingsTabs />

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="text-sm text-emerald-700 dark:text-emerald-400">
          {notice}
        </p>
      ) : null}

      <div className="card space-y-4 p-4">
        <div>
          <p className={labelCls}>Data controller</p>
          <p className={hintCls}>
            Candidates see this on the privacy notice as the entity responsible for their
            data. Use your registered legal name.
          </p>
        </div>
        <div>
          <label htmlFor="legal-name" className="mb-1 block text-[12.5px] font-medium text-g700">
            Legal entity name
          </label>
          <input
            id="legal-name"
            type="text"
            value={legalName}
            onChange={(event) => setLegalName(event.target.value)}
            placeholder={company.name}
            maxLength={200}
            className={inputCls}
          />
          <p className={`mt-1 ${hintCls}`}>Empty = your display name “{company.name}”.</p>
        </div>
        <div>
          <label
            htmlFor="privacy-contact"
            className="mb-1 block text-[12.5px] font-medium text-g700"
          >
            Privacy contact email
          </label>
          <input
            id="privacy-contact"
            type="email"
            value={contactEmail}
            onChange={(event) => setContactEmail(event.target.value)}
            placeholder="privacy@yourcompany.com"
            className={inputCls}
          />
          <p className={`mt-1 ${hintCls}`}>
            Where candidates send data requests (access, correction, deletion). Shown on the
            notice — set one before going live.
          </p>
        </div>
      </div>

      <div className="card space-y-3 p-4">
        <div>
          <p className={labelCls}>Retention</p>
          <p className={hintCls}>
            How long unsuccessful applications are kept after a decision, then removed.
            6 months suits the strictest EU regimes (Germany, Poland); France allows up to
            2 years.
          </p>
        </div>
        <div>
          <label htmlFor="retention" className="mb-1 block text-[12.5px] font-medium text-g700">
            Keep applications for
          </label>
          <select
            id="retention"
            value={retention === "" ? "" : String(retention)}
            onChange={(event) =>
              setRetention(event.target.value === "" ? "" : Number(event.target.value))
            }
            className="h-9 rounded-md border border-edge bg-surface px-3 text-[13.5px] outline-none focus:border-g400"
          >
            <option value="">Default — {RETENTION_DEFAULT} months</option>
            {Array.from({ length: 24 }, (_, i) => i + 1).map((months) => (
              <option key={months} value={months}>
                {months} {months === 1 ? "month" : "months"}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="card space-y-3 p-4">
        <div>
          <p className={labelCls}>Your own privacy policy</p>
          <p className={hintCls}>
            Optional. If your company already maintains a privacy policy, link it and the
            notice will point candidates there alongside the assessment-specific details.
          </p>
        </div>
        <div>
          <label htmlFor="policy-url" className="mb-1 block text-[12.5px] font-medium text-g700">
            Policy URL
          </label>
          <input
            id="policy-url"
            type="url"
            value={policyUrl}
            onChange={(event) => setPolicyUrl(event.target.value)}
            placeholder="https://yourcompany.com/privacy"
            spellCheck={false}
            className={inputCls}
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-[13.5px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : "Save privacy settings"}
        </button>
        <a
          href={`/c/${company.slug}/privacy`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 items-center gap-1.5 rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill"
        >
          <ExternalLink aria-hidden className="h-3.5 w-3.5" />
          View public notice
        </a>
      </div>
    </section>
  );
}
