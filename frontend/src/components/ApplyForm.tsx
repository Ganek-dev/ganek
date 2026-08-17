"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import { Check, FileText } from "lucide-react";

import { ApiError, publicApply } from "@/lib/api";

/** Apply flow, screens 03 (form + CV upload states) and 04 (assessment
 * invite). The CV uploads as soon as it is picked; submit stays disabled
 * until the upload finishes. All numbers shown are platform truths (24h
 * start TTL), not per-job quiz config, which is not public. */

type CvState =
  | { status: "empty" }
  | { status: "uploading"; file: File; fraction: number }
  | { status: "ready"; file: File; objectKey: string };

const inputCls =
  "h-[42px] w-full rounded-md border-[1.5px] border-edge bg-transparent px-3.5 text-[15px] text-foreground focus:border-brand focus:outline-none";
const labelCls = "text-sm font-medium";

function formatMB(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const ASSESSMENT_FACTS: [string, string][] = [
  ["1×", "one attempt — no going back between questions"],
  ["0:00", "each question locks itself when its time is up"],
  ["24h", "start any time in the next 24 hours"],
];

export function ApplyForm({
  apiBasePath,
  jobTitle,
  companyName,
  privacyHref,
}: {
  apiBasePath: string;
  jobTitle?: string;
  companyName?: string;
  privacyHref?: string;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{
    firstName: string;
    quizToken: string | null;
    statusToken: string | null;
  } | null>(
    null,
  );
  const [cv, setCv] = useState<CvState>({ status: "empty" });
  const fileRef = useRef<HTMLInputElement>(null);
  const uploadSeq = useRef(0);

  async function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    setError(null);
    if (!file || file.size === 0) {
      setCv({ status: "empty" });
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      input.value = "";
      setCv({ status: "empty" });
      setError("Your CV must be a PDF file.");
      return;
    }

    const seq = ++uploadSeq.current;
    setCv({ status: "uploading", file, fraction: 0 });
    try {
      const ticket = await publicApply.uploadTicket(apiBasePath);
      if (file.size > ticket.max_size_mb * 1024 * 1024) {
        throw new ApiError(413, `Your CV exceeds the ${ticket.max_size_mb} MB limit.`);
      }
      await publicApply.uploadCv(ticket, file, (fraction) => {
        if (uploadSeq.current === seq) setCv({ status: "uploading", file, fraction });
      });
      if (uploadSeq.current === seq) {
        setCv({ status: "ready", file, objectKey: ticket.object_key });
      }
    } catch (err) {
      if (uploadSeq.current === seq) {
        input.value = "";
        setCv({ status: "empty" });
        setError(
          err instanceof Error ? err.message : "CV upload failed — please try again",
        );
      }
    }
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (cv.status === "uploading") {
      setError("Please wait for the CV upload to finish.");
      return;
    }
    if (cv.status !== "ready") {
      setError("Please attach your CV as a PDF.");
      return;
    }

    const data = new FormData(event.currentTarget);
    const str = (name: string) => String(data.get(name) ?? "").trim();
    const opt = (name: string) => (str(name) === "" ? null : str(name));

    setBusy(true);
    try {
      const received = await publicApply.submit(apiBasePath, {
        name: str("name"),
        email: str("email"),
        message: opt("message"),
        github: opt("github"),
        linkedin: opt("linkedin"),
        portfolio: opt("portfolio"),
        cv_object_key: cv.objectKey,
        cv_filename: cv.file.name,
      });
      setDone({
        firstName: str("name").split(/\s+/)[0] ?? "",
        quizToken: received.quiz_token,
        statusToken: received.status_token,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong — please try again");
      setBusy(false);
    }
  }

  if (done) {
    const quizPath = done.quizToken ? `/quiz/${done.quizToken}` : null;
    const quizUrl =
      quizPath && typeof window !== "undefined"
        ? new URL(quizPath, window.location.origin).toString()
        : (quizPath ?? "");
    return (
      <div className="mx-auto max-w-[560px] text-center">
        <div
          className="mx-auto flex h-11 w-11 items-center justify-center rounded-full"
          style={{ background: "var(--ok-soft)" }}
        >
          <Check
            aria-hidden
            className="h-5 w-5"
            strokeWidth={2.5}
            style={{ color: "var(--ok)" }}
          />
        </div>
        <h2 className="mt-5 font-heading text-[27px] leading-[1.2] font-semibold tracking-[-0.01em]">
          Application received{done.firstName ? `, ${done.firstName}` : ""}
        </h2>
        {quizPath ? (
          <>
            <p className="mx-auto mt-3 max-w-[420px] text-[15px] leading-[23px] text-g600 [text-wrap:pretty]">
              One step left: a short skills assessment. It&apos;s how this team
              shortlists — your CV alone won&apos;t be filtered out by keywords.
            </p>
            <div className="mx-auto mt-7 max-w-[440px] rounded-xl border border-edge p-5 text-left sm:p-[22px]">
              <span className="font-heading text-[16px] font-semibold">
                Skills assessment
              </span>
              <div className="mt-3.5 flex flex-col gap-2 text-sm leading-5 text-g700">
                {ASSESSMENT_FACTS.map(([marker, fact]) => (
                  <div key={marker} className="flex gap-2.5">
                    <span className="w-[34px] shrink-0 font-mono text-xs font-semibold text-brand">
                      {marker}
                    </span>
                    <span>{fact}</span>
                  </div>
                ))}
              </div>
              <Link
                href={quizPath}
                className="mt-[18px] flex h-11 w-full items-center justify-center rounded-md bg-brand text-[15px] font-semibold text-brand-foreground hover:brightness-[0.94]"
              >
                Start assessment now
              </Link>
              <p className="mt-2.5 text-center text-[13px] text-g500">
                or later — save your personal link:
              </p>
              <input
                readOnly
                aria-label="Assessment link"
                value={quizUrl}
                onFocus={(event) => event.currentTarget.select()}
                className="mt-1.5 h-9 w-full rounded-sm border border-edge bg-transparent px-2.5 text-center font-mono text-[11.5px] text-g600 focus:outline-none"
              />
            </div>
            <p className="mt-6 font-mono text-[11px] text-g400">
              Find a quiet 10 minutes — tab switches, pastes &amp; resizes are recorded
            </p>
          </>
        ) : (
          <p className="mx-auto mt-3 max-w-[420px] text-[15px] leading-[23px] text-g600">
            Thanks for applying — the team will be in touch.
          </p>
        )}
        {done.statusToken ? (
          <p className="mt-4 text-[13px] text-g500">
            <Link
              href={`/application/${done.statusToken}`}
              className="text-brand hover:underline"
            >
              Track your application
            </Link>{" "}
            — private link, no account needed.
          </p>
        ) : null}
      </div>
    );
  }

  const uploading = cv.status === "uploading";
  const pct = uploading ? Math.round(cv.fraction * 100) : 0;

  return (
    <form onSubmit={handleSubmit} className="mx-auto max-w-[560px]">
      <h2 className="font-heading text-[26px] leading-[1.2] font-semibold tracking-[-0.01em]">
        Apply{jobTitle ? ` — ${jobTitle}` : " for this position"}
      </h2>
      <p className="mt-2.5 text-[14.5px] leading-[22px] text-g600">
        Three fields, about two minutes.
      </p>

      <div className="mt-7 flex flex-col gap-[18px]">
        <label className="block space-y-2">
          <span className={labelCls}>Name</span>
          <input name="name" required maxLength={200} className={inputCls} />
        </label>
        <label className="block space-y-2">
          <span className={labelCls}>Email</span>
          <input name="email" type="email" required className={inputCls} />
        </label>

        <div className="space-y-2">
          <label htmlFor="apply-cv" className={labelCls}>
            CV (PDF)
          </label>
          {/* no native `required`: jsdom cannot validate file inputs and the JS guard gives a friendlier message */}
          <input
            id="apply-cv"
            ref={fileRef}
            name="cv"
            type="file"
            accept="application/pdf,.pdf"
            onChange={handleFileChange}
            className={cv.status === "empty" ? inputCls + " py-2" : "sr-only"}
          />
          {cv.status !== "empty" ? (
            <div className="rounded-lg border-[1.5px] border-edge px-4 py-3.5">
              <div className="flex items-center gap-3">
                <FileText aria-hidden className="h-[18px] w-[18px] shrink-0 text-g500" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{cv.file.name}</div>
                  <div className="mt-0.5 font-mono text-[11px] text-g500">
                    {uploading
                      ? `uploading — ${pct}% of ${formatMB(cv.file.size)}`
                      : `uploaded · ${formatMB(cv.file.size)}`}
                  </div>
                </div>
                {uploading ? (
                  <span className="shrink-0 font-mono text-xs text-brand">{pct}%</span>
                ) : (
                  <button
                    type="button"
                    onClick={() => fileRef.current?.click()}
                    className="shrink-0 text-[13px] text-g500 underline hover:text-foreground"
                  >
                    Replace
                  </button>
                )}
              </div>
              {uploading ? (
                <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-divider">
                  <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-8">
        <span className="overline text-g500">Optional</span>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <label className="block space-y-2">
            <span className={labelCls}>GitHub</span>
            <input name="github" type="url" placeholder="https://" className={inputCls} />
          </label>
          <label className="block space-y-2">
            <span className={labelCls}>LinkedIn</span>
            <input name="linkedin" type="url" placeholder="https://" className={inputCls} />
          </label>
          <label className="block space-y-2">
            <span className={labelCls}>Portfolio</span>
            <input name="portfolio" type="url" placeholder="https://" className={inputCls} />
          </label>
        </div>
        <label className="mt-4 block space-y-2">
          <span className={labelCls}>Message (optional)</span>
          <textarea
            name="message"
            rows={4}
            maxLength={5000}
            className="w-full rounded-md border-[1.5px] border-edge bg-transparent px-3.5 py-2.5 text-[15px] text-foreground focus:border-brand focus:outline-none"
          />
          {/* Art. 9 minimization nudge — special-category data is not sought */}
          <span className="block text-[12.5px] leading-[18px] text-g500">
            Please leave out sensitive personal details (health, beliefs, family situation) —
            they play no part in the review.
          </span>
        </label>
      </div>

      {error ? (
        <p role="alert" className="mt-4 text-sm" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      ) : null}

      {privacyHref ? (
        // Art. 13 short layer at the point of collection. Deliberately a
        // notice, not a consent checkbox — the basis is 6(1)(b).
        <p className="mt-6 text-[12.5px] leading-[18px] text-g500">
          By applying, {companyName ?? "the company"} processes your details to consider
          you for this role. How it&apos;s handled, how long it&apos;s kept, and your
          rights:{" "}
          <a href={privacyHref} target="_blank" rel="noreferrer" className="underline">
            privacy notice
          </a>
          .
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy || uploading}
        className="mt-7 flex h-[46px] w-full items-center justify-center rounded-md bg-brand text-[15px] font-semibold text-brand-foreground hover:brightness-[0.94] disabled:bg-muted-fill disabled:text-g500 disabled:hover:brightness-100"
      >
        {busy ? "Submitting…" : "Submit application"}
      </button>
      {uploading ? (
        <p className="mt-3 text-center font-mono text-[11px] text-g400">
          Waiting for upload to finish…
        </p>
      ) : null}
    </form>
  );
}
