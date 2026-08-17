"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { GripVertical, Search, Trash2, X } from "lucide-react";

import { DifficultyDots } from "@/components/DifficultyDots";
import { Switch } from "@/components/ui/switch";
import {
  questionnaires,
  questions,
  type BankPage,
  type QuestionnaireOut,
  type ResolvedQuestion,
} from "@/lib/api";

/** Questionnaire builder, handoff screen 16: editable title, difficulty-mix
 * summary, shuffle toggle, drag-to-reorder rows on the left; live library
 * search on the right with +Add / added indicators. Timing is deferred to
 * the attached job's quiz_config (there is no per-questionnaire time field
 * in the model), so the segmented control from the mock is intentionally
 * omitted here — the job form still owns it. */

const LIBRARY_PAGE_SIZE = 25;
const SAVE_DEBOUNCE_MS = 600;

type SavingState = "clean" | "dirty" | "saving" | "saved" | "error";

function stemFor(prompt: string): string {
  const oneLine = prompt.replace(/\s+/g, " ").trim();
  return oneLine.length > 140 ? `${oneLine.slice(0, 137)}…` : oneLine;
}

function totalTimeLabel(seconds: number): string {
  if (seconds <= 0) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  if (minutes === 0) return `${seconds}s`;
  if (rest === 0) return `~${minutes} min`;
  return `~${minutes}m ${rest}s`;
}

function MixBar({ items }: { items: ResolvedQuestion[] }) {
  const total = items.length;
  const easy = items.filter((q) => q.difficulty <= 2).length;
  const medium = items.filter((q) => q.difficulty === 3).length;
  const hard = items.filter((q) => q.difficulty >= 4).length;
  const totalSeconds = items.reduce((sum, q) => sum + q.time_limit_seconds, 0);

  if (total === 0) {
    return (
      <p className="font-mono text-[10.5px] text-g500">
        empty — add questions from the library on the right.
      </p>
    );
  }

  return (
    <div>
      <div className="flex h-[7px] overflow-hidden rounded-full">
        <span
          className="block bg-emerald-200 dark:bg-emerald-900"
          style={{ width: `${(easy / total) * 100}%` }}
        />
        <span
          className="block bg-amber-200 dark:bg-amber-900"
          style={{ width: `${(medium / total) * 100}%` }}
        />
        <span
          className="block bg-red-200 dark:bg-red-900"
          style={{ width: `${(hard / total) * 100}%` }}
        />
      </div>
      <p className="mt-2 font-mono text-[10.5px] text-g500">
        {total} question{total === 1 ? "" : "s"} · {easy} easy · {medium} medium · {hard} hard ·{" "}
        {totalTimeLabel(totalSeconds)} total
      </p>
    </div>
  );
}

function LibraryRow({
  question,
  added,
  onAdd,
}: {
  question: ResolvedQuestion;
  added: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="flex items-center gap-2.5 border-b border-divider py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <p className="truncate text-[12.5px] font-medium leading-[18px]">
          {stemFor(question.prompt_md)}
        </p>
        <p className="mt-0.5 truncate font-mono text-[10px] text-g400">
          {[...question.tags, `d${question.difficulty}`, question.source === "seed" ? "bank" : "company"].join(
            " · ",
          )}
        </p>
      </div>
      {added ? (
        <span className="inline-flex shrink-0 items-center gap-1 font-mono text-[10.5px] text-emerald-700 dark:text-emerald-400">
          added
        </span>
      ) : (
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex h-[26px] shrink-0 items-center rounded-md border border-edge bg-surface px-2.5 text-[11.5px] font-semibold text-accent hover:border-accent"
        >
          + Add
        </button>
      )}
    </div>
  );
}

interface BuilderRowProps {
  index: number;
  question: ResolvedQuestion | undefined;
  refId: string;
  onRemove: () => void;
  isDragging: boolean;
  onDragStart: () => void;
  onDragOver: (event: React.DragEvent<HTMLLIElement>) => void;
  onDragEnd: () => void;
  onDrop: () => void;
}

function BuilderRow({
  index,
  question,
  refId,
  onRemove,
  isDragging,
  onDragStart,
  onDragOver,
  onDragEnd,
  onDrop,
}: BuilderRowProps) {
  return (
    <li
      draggable
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      className={`flex items-center gap-3 border-b border-divider px-4 py-3 last:border-b-0 hover:bg-hover-fill ${
        isDragging ? "opacity-40" : ""
      }`}
    >
      <GripVertical
        aria-hidden
        className="h-3.5 w-3.5 shrink-0 cursor-grab text-g400"
      />
      <span className="w-6 shrink-0 font-mono text-[11px] text-g400">{index + 1}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13.5px] font-medium">
          {question ? stemFor(question.prompt_md) : `Missing question ${refId}`}
        </p>
        {question ? (
          <div className="mt-1 flex flex-wrap items-center gap-2.5 font-mono text-[10.5px] text-g500">
            <span>{question.source === "seed" ? "bank" : "company"}</span>
            <DifficultyDots level={question.difficulty} />
            <span>{question.tags.slice(0, 3).join(" · ")}</span>
            {question.status === "retired" ? (
              <span className="text-amber-700 dark:text-amber-400">retired</span>
            ) : null}
          </div>
        ) : (
          <p className="mt-1 font-mono text-[10.5px] text-amber-700 dark:text-amber-400">
            not visible to this workspace — remove to clean up
          </p>
        )}
      </div>
      {question ? (
        <span className="inline-flex h-5 shrink-0 items-center rounded-full bg-muted-fill px-2 font-mono text-[10.5px] text-g600">
          {question.time_limit_seconds}s
        </span>
      ) : null}
      <button
        type="button"
        aria-label="Remove from questionnaire"
        onClick={onRemove}
        className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-sm text-g400 hover:bg-muted-fill hover:text-red-600 dark:hover:text-red-400"
      >
        <X aria-hidden className="h-3.5 w-3.5" />
      </button>
    </li>
  );
}

export default function QuestionnaireBuilderPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const [questionnaire, setQuestionnaire] = useState<QuestionnaireOut | null>(null);
  const [name, setName] = useState("");
  const [shuffle, setShuffle] = useState(false);
  const [refs, setRefs] = useState<string[]>([]);
  // null = we asked and the workspace can't see it (the builder shows a
  // "missing" warning row); undefined = we haven't asked yet.
  const [resolved, setResolved] = useState<Record<string, ResolvedQuestion | null>>({});
  const [libraryQuery, setLibraryQuery] = useState("");
  const [library, setLibrary] = useState<BankPage | null>(null);
  const [saving, setSaving] = useState<SavingState>("clean");
  const [error, setError] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<{ name: string; shuffle: boolean; refs: string[] } | null>(null);

  useEffect(() => {
    questionnaires
      .get(params.id)
      .then((row) => {
        setQuestionnaire(row);
        setName(row.name);
        setShuffle(row.shuffle);
        setRefs(row.question_refs);
        lastSavedRef.current = {
          name: row.name,
          shuffle: row.shuffle,
          refs: [...row.question_refs],
        };
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Failed to load questionnaire"),
      );
  }, [params.id]);

  // Resolve the currently-referenced questions whenever refs change; keep a
  // cache so scrubbing through drag-to-reorder doesn't re-fetch each move.
  // Refs we already asked about (whether found or not) are skipped — we mark
  // "not found" as `null` in the cache so the effect can't infinite-loop.
  useEffect(() => {
    const missing = refs.filter((ref) => !(ref in resolved));
    if (missing.length === 0) return;
    let cancelled = false;
    questions
      .resolve(missing)
      .then((rows) => {
        if (cancelled) return;
        const returned = new Set(rows.map((row) => row.id));
        setResolved((prev) => {
          const next = { ...prev };
          for (const row of rows) next[row.id] = row;
          for (const ref of missing) {
            if (!returned.has(ref)) next[ref] = null;
          }
          return next;
        });
      })
      .catch(() => {
        if (cancelled) return;
        // best-effort — mark as tried so we don't retry-loop
        setResolved((prev) => {
          const next = { ...prev };
          for (const ref of missing) {
            if (!(ref in next)) next[ref] = null;
          }
          return next;
        });
      });
    return () => {
      cancelled = true;
    };
  }, [refs, resolved]);

  const reloadLibrary = useCallback(() => {
    questions
      .bank({ q: libraryQuery || undefined, limit: LIBRARY_PAGE_SIZE })
      .then(setLibrary)
      .catch(() => setLibrary(null));
  }, [libraryQuery]);
  useEffect(reloadLibrary, [reloadLibrary]);

  // Debounced save — snapshot the last committed state so we don't PATCH
  // no-op updates. Runs whenever name/shuffle/refs change post-load.
  useEffect(() => {
    if (questionnaire === null) return;
    const snapshot = { name, shuffle, refs };
    const last = lastSavedRef.current;
    const dirty =
      last === null ||
      last.name !== snapshot.name ||
      last.shuffle !== snapshot.shuffle ||
      last.refs.length !== snapshot.refs.length ||
      last.refs.some((ref, i) => ref !== snapshot.refs[i]);
    if (!dirty) return;
    setSaving("dirty");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaving("saving");
      try {
        const updated = await questionnaires.update(questionnaire.id, {
          name: snapshot.name.trim() || "Untitled",
          shuffle: snapshot.shuffle,
          question_refs: snapshot.refs,
        });
        setQuestionnaire(updated);
        lastSavedRef.current = {
          name: updated.name,
          shuffle: updated.shuffle,
          refs: [...updated.question_refs],
        };
        setSaving("saved");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Save failed");
        setSaving("error");
      }
    }, SAVE_DEBOUNCE_MS);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [name, shuffle, refs, questionnaire]);

  const attachedRows = useMemo(
    () => refs.map((ref) => resolved[ref] ?? undefined),
    [refs, resolved],
  );
  const attachedResolved = attachedRows.filter(
    (row): row is ResolvedQuestion => row !== undefined,
  );

  function addRef(refId: string) {
    if (refs.includes(refId)) return;
    setRefs((current) => [...current, refId]);
  }

  function removeRef(refId: string) {
    setRefs((current) => current.filter((ref) => ref !== refId));
  }

  async function handleDelete() {
    if (!questionnaire) return;
    if (!window.confirm(`Delete questionnaire "${questionnaire.name}"?`)) return;
    try {
      await questionnaires.delete(questionnaire.id);
      router.push("/admin/questionnaires");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  function onDragStart(index: number) {
    setDragIndex(index);
  }
  function onDragOver(index: number, event: React.DragEvent<HTMLLIElement>) {
    event.preventDefault();
    if (dragIndex === null || dragIndex === index) return;
    setRefs((current) => {
      const next = [...current];
      const [moved] = next.splice(dragIndex, 1);
      next.splice(index, 0, moved);
      return next;
    });
    setDragIndex(index);
  }
  function onDragEnd() {
    setDragIndex(null);
  }

  const attachedSet = new Set(refs);

  if (error && questionnaire === null) {
    return (
      <p role="alert" className="text-sm text-red-600 dark:text-red-400">
        {error}
      </p>
    );
  }
  if (questionnaire === null) {
    return (
      <section aria-busy="true" className="space-y-4">
        <div className="h-8 w-64 animate-pulse rounded-sm bg-muted-fill" />
        <div className="h-96 animate-pulse rounded-lg bg-muted-fill" />
      </section>
    );
  }

  const savingLabel: Record<SavingState, string> = {
    clean: "",
    dirty: "unsaved changes…",
    saving: "saving…",
    saved: "saved",
    error: "save failed",
  };

  return (
    <section className="space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="font-mono text-[11.5px] text-g500">
            <Link href="/admin/questionnaires" className="hover:text-accent">
              Questionnaires
            </Link>{" "}
            / {questionnaire.name}
          </p>
          <div className="mt-1.5 flex items-center gap-3">
            <input
              aria-label="Questionnaire name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="min-w-0 flex-1 border-b-[1.5px] border-dashed border-edge bg-transparent pb-0.5 font-heading text-[22px] font-semibold tracking-[-0.01em] outline-none focus:border-accent"
            />
            <span
              aria-live="polite"
              className={`font-mono text-[11px] ${
                saving === "error"
                  ? "text-red-600 dark:text-red-400"
                  : saving === "saved"
                    ? "text-emerald-700 dark:text-emerald-400"
                    : "text-g500"
              }`}
            >
              {savingLabel[saving]}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={handleDelete}
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-edge bg-surface px-3 text-[13px] font-medium text-g700 hover:bg-muted-fill"
        >
          <Trash2 aria-hidden className="h-3.5 w-3.5" />
          Delete
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[1fr_400px]">
        <div>
          <div className="card flex items-center gap-6 px-[18px] py-3.5">
            <div className="min-w-0 flex-1">
              <MixBar items={attachedResolved} />
            </div>
            <label className="flex shrink-0 items-center gap-2 text-[12.5px] text-g700">
              <span>Shuffle</span>
              <Switch
                size="sm"
                checked={shuffle}
                aria-label="Shuffle question order"
                onCheckedChange={setShuffle}
              />
            </label>
          </div>

          <div className="card mt-3.5 overflow-hidden">
            {refs.length === 0 ? (
              <p className="p-8 text-center text-sm text-g500">
                No questions yet. Add from the library on the right, or write a new one in the{" "}
                <Link href="/admin/questions" className="text-accent hover:underline">
                  question library
                </Link>
                .
              </p>
            ) : (
              <ul>
                {refs.map((refId, index) => (
                  <BuilderRow
                    key={refId}
                    index={index}
                    question={resolved[refId] ?? undefined}
                    refId={refId}
                    onRemove={() => removeRef(refId)}
                    isDragging={dragIndex === index}
                    onDragStart={() => onDragStart(index)}
                    onDragOver={(event) => onDragOver(index, event)}
                    onDragEnd={onDragEnd}
                    onDrop={onDragEnd}
                  />
                ))}
              </ul>
            )}
            {refs.length > 0 ? (
              <p className="border-t border-divider py-3 text-center font-mono text-[11px] text-g400">
                drag to reorder — order is what candidates see unless shuffled
              </p>
            ) : null}
          </div>
        </div>

        <div className="card px-[18px] py-4">
          <div className="font-heading text-[15px] font-semibold">Add from library</div>
          <div className="relative mt-3">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-[11px] h-[14px] w-[14px] -translate-y-1/2 text-g400"
            />
            <input
              aria-label="Search library"
              placeholder="Search questions…"
              value={libraryQuery}
              onChange={(event) => setLibraryQuery(event.target.value)}
              className="h-8 w-full rounded-md border border-edge bg-transparent pr-3 pl-8 text-[13px] outline-none focus:border-g400"
            />
          </div>
          <div className="mt-3 flex flex-col">
            {library === null ? (
              <div aria-busy="true" className="space-y-2">
                {Array.from({ length: 5 }, (_, i) => (
                  <div key={i} className="h-11 animate-pulse rounded-sm bg-muted-fill" />
                ))}
              </div>
            ) : library.items.length === 0 ? (
              <p className="py-6 text-center text-sm text-g500">No questions match.</p>
            ) : (
              library.items.map((row) => (
                <LibraryRow
                  key={row.id}
                  question={{
                    id: row.id,
                    prompt_md: row.prompt_md,
                    tags: row.tags,
                    difficulty: row.difficulty,
                    time_limit_seconds: row.time_limit_seconds,
                    source: "seed",
                    status: "active",
                    blocked: row.blocked,
                  }}
                  added={attachedSet.has(row.id)}
                  onAdd={() => addRef(row.id)}
                />
              ))
            )}
            <Link
              href="/admin/questions"
              className="mt-3 inline-flex h-[30px] w-full items-center justify-center rounded-md border border-dashed border-edge text-[12px] font-medium text-g500 hover:border-accent hover:text-accent"
            >
              + Write a new question
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}
