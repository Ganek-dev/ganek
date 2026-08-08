"use client";

import { useEffect, useState } from "react";

import { SettingsTabs } from "@/components/SettingsTabs";
import { companyApi } from "@/lib/api";

/** Hiring behavior settings (D6): what happens when a candidate's expired
 * assessment link asks for a re-issue (27c). Companion to the branding tab;
 * more hiring settings land here as they ship. */

type ReissueMode = "manual" | "auto";

const OPTIONS: { value: ReissueMode; title: string; description: string }[] = [
  {
    value: "manual",
    title: "Ask the team first",
    description:
      "Requests show up on the applicant for a recruiter to re-issue — nothing goes out automatically.",
  },
  {
    value: "auto",
    title: "Re-issue automatically, once",
    description:
      "The first request emails a fresh link right away; any further requests still need a recruiter. The lateness stays visible on the applicant either way.",
  },
];

export default function HiringSettingsPage() {
  const [mode, setMode] = useState<ReissueMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    companyApi
      .get()
      .then((company) => setMode(company.settings.quiz_expired_reissue ?? "manual"))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load settings"),
      );
  }, []);

  async function pick(next: ReissueMode) {
    const previous = mode;
    setError(null);
    setNotice(null);
    setMode(next);
    try {
      await companyApi.updateSettings({
        quiz_expired_reissue: next === "manual" ? null : next,
      });
      setNotice("Saved");
    } catch (err) {
      setMode(previous);
      setError(err instanceof Error ? err.message : "Failed to save");
    }
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

      <div className="card p-4">
        <p className="text-[13.5px] font-semibold">Expired assessment links</p>
        <p className="mt-1 text-[12.5px] leading-[18px] text-g500">
          When a candidate&apos;s link runs out and they ask for a new one from the expired
          screen.
        </p>
        {mode === null ? (
          <div aria-busy="true" className="mt-3 space-y-2">
            <div className="h-16 animate-pulse rounded-md bg-muted-fill" />
            <div className="h-16 animate-pulse rounded-md bg-muted-fill" />
          </div>
        ) : (
          <div role="radiogroup" aria-label="Expired-link re-issue" className="mt-3 space-y-2">
            {OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="radio"
                aria-checked={mode === option.value}
                onClick={() => pick(option.value)}
                className={`block w-full rounded-md border p-3 text-left ${
                  mode === option.value
                    ? "border-accent bg-accent/5"
                    : "border-edge hover:bg-muted-fill"
                }`}
              >
                <span className="block text-[13.5px] font-medium">{option.title}</span>
                <span className="mt-0.5 block text-[12.5px] leading-[18px] text-g500">
                  {option.description}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
