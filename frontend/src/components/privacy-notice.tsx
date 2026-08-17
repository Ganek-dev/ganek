import Link from "next/link";

import { brandStyle } from "@/lib/brand";
import type { PublicPrivacyNotice } from "@/lib/public-api";

/** Candidate privacy notice (M5.6 G1): the Art. 13 full layer, rendered from
 * platform truth + the company's privacy settings. Every claim here must
 * stay in sync with what the code actually does — the integrity-signal list
 * (blur/paste/resize), the no-cookies line, and the no-auto-reject guarantee
 * are audited facts, not boilerplate. */

function months(n: number): string {
  return n === 1 ? "1 month" : `${n} months`;
}

const h2Cls = "font-heading text-[17px] font-semibold tracking-[-0.01em]";
const pCls = "mt-2 text-[14.5px] leading-[22px] text-g600";
const liCls = "text-[14.5px] leading-[22px] text-g600";
const termCls = "font-medium text-foreground";

export function PrivacyNotice({
  notice,
  backHref,
}: {
  notice: PublicPrivacyNotice;
  backHref: string;
}) {
  const contact = notice.privacy_contact_email;
  return (
    <main
      className="min-h-screen bg-surface text-foreground"
      style={brandStyle(notice.brand_primary ?? undefined)}
    >
      <div className="mx-auto max-w-[720px] px-5 pt-10 pb-14 sm:px-6">
        <header className="flex items-center gap-2.5">
          {notice.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- served by the instance's own API
            <img
              src={notice.logo_url}
              alt=""
              className="h-7 w-7 rounded-md bg-white object-contain"
            />
          ) : (
            <span
              aria-hidden
              className="flex h-7 w-7 items-center justify-center rounded-md text-[13px] font-bold"
              style={{
                background: "var(--brand-primary)",
                color: "var(--brand-primary-foreground)",
              }}
            >
              {notice.company_name.charAt(0).toUpperCase()}
            </span>
          )}
          <span className="text-sm font-semibold">{notice.company_name}</span>
          <span className="ml-auto font-mono text-[11px] text-g400">Careers · Privacy</span>
        </header>

        <h1 className="mt-8 font-heading text-[26px] leading-[1.2] font-semibold tracking-[-0.01em]">
          How {notice.company_name} handles your application data
        </h1>
        <p className={pCls}>
          <span className={termCls}>{notice.legal_name}</span> is the data controller for
          applications made on this careers site. The site runs on Vetd, an open-source
          hiring platform.
        </p>

        {notice.privacy_policy_url ? (
          <a
            href={notice.privacy_policy_url}
            target="_blank"
            rel="noreferrer"
            className="mt-4 block rounded-lg border-[1.5px] border-edge px-4 py-3.5 text-[14px] font-medium hover:bg-muted-fill"
          >
            {notice.company_name} also maintains its own privacy policy — read it here.
            <span className="mt-0.5 block text-[12.5px] font-normal text-g500">
              The points below cover what happens on this careers site specifically.
            </span>
          </a>
        ) : null}

        <section className="mt-8">
          <h2 className={h2Cls}>What this site collects</h2>
          <ul className="mt-2 list-disc space-y-1.5 pl-5">
            <li className={liCls}>
              <span className={termCls}>Your application</span> — name, email, CV file, and
              the optional links and message you choose to add. Please don&apos;t include
              sensitive personal details (health, beliefs, and similar) in your CV or
              message — they aren&apos;t asked for or wanted.
            </li>
            <li className={liCls}>
              <span className={termCls}>Assessment answers</span> — if this role includes a
              screening assessment: your answers, per-question response times, and score.
            </li>
            <li className={liCls}>
              <span className={termCls}>Assessment integrity signals</span> — during a timed
              assessment only: tab switches (with how long you were away), pastes, and
              window resizes, each tied to the question that was open. Nothing else — no
              keystrokes, no screen contents, no location.
            </li>
            <li className={liCls}>
              <span className={termCls}>Interview scheduling</span> — if you&apos;re
              invited: the time slot you pick.
            </li>
          </ul>
        </section>

        <section className="mt-7">
          <h2 className={h2Cls}>Why, and on what legal basis</h2>
          <ul className="mt-2 list-disc space-y-1.5 pl-5">
            <li className={liCls}>
              <span className={termCls}>Considering your application</span> — the steps you
              ask for by applying (GDPR art. 6(1)(b)). No consent checkbox is needed for
              this, and none is asked.
            </li>
            <li className={liCls}>
              <span className={termCls}>Keeping assessments fair</span> — integrity signals
              are collected on legitimate-interest grounds (art. 6(1)(f)). People review
              them; they never change your score and never reject anyone automatically.
            </li>
            <li className={liCls}>
              <span className={termCls}>After a decision</span> — applications are kept for
              a limited period (below) so hiring decisions can be reviewed and defended
              (art. 6(1)(f)).
            </li>
          </ul>
        </section>

        <section className="mt-7">
          <h2 className={h2Cls}>Who sees your data</h2>
          <ul className="mt-2 list-disc space-y-1.5 pl-5">
            <li className={liCls}>
              The {notice.company_name} hiring team, on this platform.
            </li>
            <li className={liCls}>
              The infrastructure this site runs on — servers, file storage for CVs, and the
              email delivery service.
            </li>
            <li className={liCls}>
              <span className={termCls}>Google (Calendar &amp; Meet)</span> — only if an
              interview is scheduled: your name and email go into the calendar event, and
              Google emails you the invite. Google is a US company; the transfer relies on
              the EU–US Data Privacy Framework and Google&apos;s standard data-protection
              terms.
            </li>
          </ul>
        </section>

        <section className="mt-7">
          <h2 className={h2Cls}>How long it&apos;s kept</h2>
          <p className={pCls}>
            Unsuccessful and withdrawn applications are removed{" "}
            <span className={termCls}>{months(notice.retention_months)}</span> after the
            decision. If you&apos;re hired, your application becomes part of your employment
            records instead.
          </p>
          <p className={pCls}>
            The private links you receive expire on their own: status links after 30 days,
            interview booking links after 60 days, and assessment links at the deadline
            stated in the invitation.
          </p>
        </section>

        <section className="mt-7">
          <h2 className={h2Cls}>Your rights</h2>
          <p className={pCls}>
            You can ask for a copy of your data, have it corrected or deleted, restrict or
            object to how it&apos;s used, and receive it in a portable format.
          </p>
          <p className={pCls}>
            {contact ? (
              <>
                To exercise any of these, email{" "}
                <a href={`mailto:${contact}`} className="font-medium underline">
                  {contact}
                </a>
                .
              </>
            ) : (
              <>To exercise any of these, contact {notice.company_name} directly.</>
            )}{" "}
            You can also complain to your local data-protection authority.
          </p>
        </section>

        <section className="mt-7">
          <h2 className={h2Cls}>What this site doesn&apos;t do</h2>
          <ul className="mt-2 list-disc space-y-1.5 pl-5">
            <li className={liCls}>
              <span className={termCls}>No automated decisions</span> — scores and
              integrity signals inform people; no one is rejected by a machine.
            </li>
            <li className={liCls}>
              <span className={termCls}>No trackers</span> — this careers site sets no
              cookies and runs no analytics.
            </li>
            <li className={liCls}>
              <span className={termCls}>No silent deletion of your say</span> — withdrawing
              your application (from your status page) stops it being considered; the data
              still follows the retention period above unless you request deletion sooner.
            </li>
          </ul>
        </section>

        <footer className="mt-10 border-t border-divider pt-5">
          <Link href={backHref} className="text-[13.5px] font-medium underline">
            ← Back to careers
          </Link>
        </footer>
      </div>
    </main>
  );
}
