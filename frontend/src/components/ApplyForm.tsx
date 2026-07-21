"use client";

import { useState } from "react";

import { ApiError, publicApply } from "@/lib/api";

const inputCls =
  "w-full rounded-md border border-zinc-300 px-3 py-2 text-sm text-zinc-900 focus:border-zinc-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100";
const labelCls = "text-sm font-medium text-zinc-700 dark:text-zinc-300";

export function ApplyForm({ apiBasePath }: { apiBasePath: string }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const data = new FormData(event.currentTarget);
    // read the file off the input element: works in browsers and in jsdom,
    // whose FormData does not surface file-input contents
    const fileInput = event.currentTarget.elements.namedItem("cv") as HTMLInputElement | null;
    const file = fileInput?.files?.[0];
    if (!file || file.size === 0) {
      setError("Please attach your CV as a PDF.");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Your CV must be a PDF file.");
      return;
    }

    const str = (name: string) => String(data.get(name) ?? "").trim();
    const opt = (name: string) => (str(name) === "" ? null : str(name));

    setBusy(true);
    try {
      const ticket = await publicApply.uploadTicket(apiBasePath);
      if (file.size > ticket.max_size_mb * 1024 * 1024) {
        throw new ApiError(413, `Your CV exceeds the ${ticket.max_size_mb} MB limit.`);
      }
      await publicApply.uploadCv(ticket, file);
      await publicApply.submit(apiBasePath, {
        name: str("name"),
        email: str("email"),
        message: opt("message"),
        github: opt("github"),
        linkedin: opt("linkedin"),
        portfolio: opt("portfolio"),
        cv_object_key: ticket.object_key,
        cv_filename: file.name,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong — please try again");
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="rounded-xl border border-green-200 bg-green-50 p-6 dark:border-green-900 dark:bg-green-950">
        <h2 className="font-semibold text-green-900 dark:text-green-100">
          Application received
        </h2>
        <p className="mt-1 text-sm text-green-800 dark:text-green-200">
          Thanks for applying — the team will be in touch.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-xl space-y-4">
      <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
        Apply for this position
      </h2>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="block space-y-1">
          <span className={labelCls}>Name</span>
          <input name="name" required maxLength={200} className={inputCls} />
        </label>
        <label className="block space-y-1">
          <span className={labelCls}>Email</span>
          <input name="email" type="email" required className={inputCls} />
        </label>
      </div>

      <label className="block space-y-1">
        <span className={labelCls}>CV (PDF)</span>
        {/* no native `required`: jsdom cannot validate file inputs and the JS guard below gives a friendlier message */}
        <input name="cv" type="file" accept="application/pdf,.pdf" className={inputCls} />
      </label>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <label className="block space-y-1">
          <span className={labelCls}>GitHub</span>
          <input name="github" type="url" placeholder="https://" className={inputCls} />
        </label>
        <label className="block space-y-1">
          <span className={labelCls}>LinkedIn</span>
          <input name="linkedin" type="url" placeholder="https://" className={inputCls} />
        </label>
        <label className="block space-y-1">
          <span className={labelCls}>Portfolio</span>
          <input name="portfolio" type="url" placeholder="https://" className={inputCls} />
        </label>
      </div>

      <label className="block space-y-1">
        <span className={labelCls}>Message (optional)</span>
        <textarea name="message" rows={4} maxLength={5000} className={inputCls} />
      </label>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <button
        type="submit"
        disabled={busy}
        className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
      >
        {busy ? "Submitting…" : "Submit application"}
      </button>
    </form>
  );
}
