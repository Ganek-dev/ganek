"use client";

import { useEffect, useState } from "react";

import { ExternalLink } from "lucide-react";

import { AccessLogSection } from "@/components/AccessLogSection";
import { SettingsTabs } from "@/components/SettingsTabs";
import { companyApi, healthApi, type CompanyAdmin } from "@/lib/api";
import { formatAge, useLocale } from "@/lib/i18n/locale";

/** Privacy settings (M5.6 G1): the per-company variables the candidate
 * privacy notice renders - controller identity, rights contact, retention
 * window, optional own-policy link. The notice itself lives on the public
 * careers site; this tab only feeds it. */

const RETENTION_DEFAULT = 6;

const labelCls = "text-[13.5px] font-semibold";
const hintCls = "text-[12.5px] leading-[18px] text-g500";
const inputCls =
  "h-9 w-full rounded-md border border-edge bg-transparent px-3 text-[13.5px] outline-none focus:border-g400";

export default function PrivacySettingsPage() {
  const { t } = useLocale();
  const [company, setCompany] = useState<CompanyAdmin | null>(null);
  const [legalName, setLegalName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [retention, setRetention] = useState<number | "">("");
  const [policyUrl, setPolicyUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  // undefined = still loading, null = never ran or unknown (deep health failed)
  const [lastPurgeAt, setLastPurgeAt] = useState<string | null | undefined>(undefined);
  const [purgeKnown, setPurgeKnown] = useState(true);

  async function sendTest() {
    setTestResult(null);
    setTestBusy(true);
    try {
      await companyApi.testEmail();
      setTestResult({ ok: true, message: t("privacy.testSent") });
    } catch (err) {
      setTestResult({
        ok: false,
        message: err instanceof Error ? err.message : t("privacy.testFailed"),
      });
    } finally {
      setTestBusy(false);
    }
  }

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
        setError(err instanceof Error ? err.message : t("privacy.loadFailed")),
      );
    healthApi
      .deep()
      .then((health) => setLastPurgeAt(health.worker.last_purge_at))
      .catch(() => {
        // a 503 (some dependency down) or a network error: the answer to
        // "did last night's purge run?" is simply not available right now
        setPurgeKnown(false);
        setLastPurgeAt(null);
      });
    // load once on mount; a language switch only re-labels what is on screen
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setNotice(t("privacy.saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("privacy.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  if (company === null) {
    return (
      <section className="max-w-[680px] space-y-4">
        <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">{t("privacy.title")}</h1>
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
      <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">{t("privacy.title")}</h1>
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
          <p className={labelCls}>{t("privacy.controllerTitle")}</p>
          <p className={hintCls}>{t("privacy.controllerHint")}</p>
        </div>
        <div>
          <label htmlFor="legal-name" className="mb-1 block text-[12.5px] font-medium text-g700">
            {t("privacy.legalName")}
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
          <p className={`mt-1 ${hintCls}`}>{t("privacy.legalNameEmpty", { name: company.name })}</p>
        </div>
        <div>
          <label
            htmlFor="privacy-contact"
            className="mb-1 block text-[12.5px] font-medium text-g700"
          >
            {t("privacy.contactEmail")}
          </label>
          <input
            id="privacy-contact"
            type="email"
            value={contactEmail}
            onChange={(event) => setContactEmail(event.target.value)}
            placeholder="privacy@yourcompany.com"
            className={inputCls}
          />
          <p className={`mt-1 ${hintCls}`}>{t("privacy.contactHint")}</p>
        </div>
      </div>

      <div className="card space-y-3 p-4">
        <div>
          <p className={labelCls}>{t("privacy.retentionTitle")}</p>
          <p className={hintCls}>{t("privacy.retentionHint")}</p>
        </div>
        <div>
          <label htmlFor="retention" className="mb-1 block text-[12.5px] font-medium text-g700">
            {t("privacy.keepFor")}
          </label>
          <select
            id="retention"
            value={retention === "" ? "" : String(retention)}
            onChange={(event) =>
              setRetention(event.target.value === "" ? "" : Number(event.target.value))
            }
            className="h-9 rounded-md border border-edge bg-surface px-3 text-[13.5px] outline-none focus:border-g400"
          >
            <option value="">{t("privacy.retentionDefault", { months: RETENTION_DEFAULT })}</option>
            {Array.from({ length: 24 }, (_, i) => i + 1).map((months) => (
              <option key={months} value={months}>
                {t(months === 1 ? "privacy.oneMonth" : "privacy.months", { count: months })}
              </option>
            ))}
          </select>
          <p className={`mt-1.5 ${hintCls}`}>
            {t("privacy.retentionNote", {
              months: retention === "" ? RETENTION_DEFAULT : retention,
            })}
          </p>
          {lastPurgeAt !== undefined ? (
            <p className={`mt-1 ${hintCls}`} data-testid="last-purge">
              {t("privacy.lastPurge", {
                when: !purgeKnown
                  ? t("privacy.purgeUnknown")
                  : lastPurgeAt === null
                    ? t("privacy.purgeNever")
                    : formatAge(t, lastPurgeAt),
              })}
            </p>
          ) : null}
        </div>
      </div>

      <div className="card space-y-3 p-4">
        <div>
          <p className={labelCls}>{t("privacy.policyTitle")}</p>
          <p className={hintCls}>{t("privacy.policyHint")}</p>
        </div>
        <div>
          <label htmlFor="policy-url" className="mb-1 block text-[12.5px] font-medium text-g700">
            {t("privacy.policyUrl")}
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

      <div className="card space-y-1 p-4">
        <p className={labelCls}>{t("privacy.scanTitle")}</p>
        <p className={hintCls}>
          {company.cv_scanning_configured ? t("privacy.scanOn") : t("privacy.scanOff")}
        </p>
      </div>

      <div className="card space-y-3 p-4">
        <div>
          <p className={labelCls}>{t("privacy.deliveryTitle")}</p>
          <p className={hintCls}>
            {company.smtp_configured ? t("privacy.smtpOn") : t("privacy.smtpOff")}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={sendTest}
            disabled={testBusy || !company.smtp_configured}
            className="inline-flex h-9 items-center rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill disabled:opacity-50"
          >
            {testBusy ? "…" : t("privacy.sendTest")}
          </button>
          {testResult ? (
            <p
              role="status"
              className={`text-[12.5px] ${
                testResult.ok
                  ? "text-emerald-700 dark:text-emerald-400"
                  : "text-red-600 dark:text-red-400"
              }`}
            >
              {testResult.message}
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-[13.5px] font-semibold text-white hover:brightness-[0.94] disabled:opacity-50"
        >
          {busy ? "…" : t("privacy.save")}
        </button>
        <a
          href={`/c/${company.slug}/privacy`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 items-center gap-1.5 rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill"
        >
          <ExternalLink aria-hidden className="h-3.5 w-3.5" />
          {t("privacy.viewNotice")}
        </a>
      </div>
      <AccessLogSection now={new Date()} />
    </section>
  );
}
