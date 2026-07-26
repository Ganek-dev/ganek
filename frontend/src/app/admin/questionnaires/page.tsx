"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ClipboardList, Plus } from "lucide-react";

import { questionnaires, type QuestionnaireOut } from "@/lib/api";

/** Questionnaire index — the D4 companion to the question library. Rows link
 * into the builder (screen 16). Row-level actions are intentionally minimal
 * here; edit lives in the builder itself. */

function relativeShort(iso: string, now: Date = new Date()): string {
  const diff = now.getTime() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.round(days / 7);
  return `${weeks}w ago`;
}

export default function QuestionnairesIndexPage() {
  const router = useRouter();
  const [items, setItems] = useState<QuestionnaireOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const reload = useCallback(() => {
    questionnaires
      .list()
      .then(setItems)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load questionnaires"),
      );
  }, []);
  useEffect(reload, [reload]);

  async function createEmpty() {
    setError(null);
    setBusy(true);
    try {
      const created = await questionnaires.create({
        name: `Untitled ${new Date().toISOString().slice(0, 10)}`,
      });
      router.push(`/admin/questionnaires/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create questionnaire");
      setBusy(false);
    }
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-[22px] font-semibold tracking-[-0.01em]">
            Questionnaires
          </h1>
          <p className="mt-1 text-[13px] text-g500">
            Curated ordered sets. Attach one to a job&apos;s assessment card to serve
            these questions instead of tag-auto selection.
          </p>
        </div>
        <button
          type="button"
          onClick={createEmpty}
          disabled={busy}
          className="inline-flex h-8 items-center gap-1.5 rounded-md bg-inverse pr-3 pl-2 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          <Plus aria-hidden className="h-[15px] w-[15px]" />
          {busy ? "…" : "New questionnaire"}
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {items === null ? (
        <div aria-busy="true" className="space-y-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-muted-fill" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="card flex flex-col items-center gap-3 p-10 text-center">
          <ClipboardList aria-hidden className="h-6 w-6 text-g400" />
          <p className="text-sm text-g500">
            No questionnaires yet.
            <br />
            Create one to curate a fixed set of questions for a role.
          </p>
          <button
            type="button"
            onClick={createEmpty}
            disabled={busy}
            className="inline-flex h-8 items-center rounded-md bg-inverse px-3 text-[13.5px] font-medium text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
          >
            {busy ? "…" : "Create the first"}
          </button>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-[13.5px]">
            <thead>
              <tr className="border-b border-divider text-left text-[12.5px] font-medium text-g500">
                <th className="h-10 px-4 font-medium">Name</th>
                <th className="h-10 px-3 font-medium">Questions</th>
                <th className="h-10 px-3 font-medium">Shuffle</th>
                <th className="h-10 px-3 font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  className="border-b border-divider last:border-b-0 hover:bg-hover-fill"
                >
                  <td className="px-4 py-3 align-middle">
                    <Link
                      href={`/admin/questionnaires/${item.id}`}
                      className="font-semibold hover:text-accent"
                    >
                      {item.name}
                    </Link>
                    {item.description ? (
                      <p className="mt-0.5 truncate text-xs text-g500">{item.description}</p>
                    ) : null}
                  </td>
                  <td className="px-3 py-3 align-middle font-mono text-[12.5px] text-g600">
                    {item.question_refs.length}
                  </td>
                  <td className="px-3 py-3 align-middle text-[12.5px] text-g600">
                    {item.shuffle ? "yes" : "no"}
                  </td>
                  <td className="px-3 py-3 align-middle font-mono text-xs text-g500">
                    {relativeShort(item.updated_at, now)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
