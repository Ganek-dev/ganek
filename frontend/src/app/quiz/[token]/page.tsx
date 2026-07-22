"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { ApiError, publicQuiz, type QuizQuestion, type QuizState } from "@/lib/api";

function useCountdown(deadline: string | null): number | null {
  // remaining time is derived at render from a ticking clock — no state
  // writes inside effects, and no bogus initial value racing the timer
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, []);
  if (!deadline) return null;
  return Math.max(0, Math.ceil((new Date(deadline).getTime() - now) / 1000));
}

type Phase = "loading" | "intro" | "question" | "done" | "expired" | "invalid";

type IntegrityEvent = {
  type: "blur" | "paste" | "resize";
  duration_ms?: number;
  question_id?: string;
};

function useIntegrityTelemetry(token: string, active: boolean, questionId: string | null) {
  const queue = useRef<IntegrityEvent[]>([]);
  const blurStarted = useRef<number | null>(null);
  const currentQuestion = useRef<string | null>(null);
  useEffect(() => {
    currentQuestion.current = questionId;
  }, [questionId]);

  useEffect(() => {
    if (!active) return;
    const onVisibility = () => {
      if (document.visibilityState === "hidden") {
        blurStarted.current = Date.now();
      } else if (blurStarted.current !== null) {
        queue.current.push({
          type: "blur",
          duration_ms: Date.now() - blurStarted.current,
          question_id: currentQuestion.current ?? undefined,
        });
        blurStarted.current = null;
      }
    };
    const onPaste = () =>
      queue.current.push({ type: "paste", question_id: currentQuestion.current ?? undefined });
    const onResize = () =>
      queue.current.push({ type: "resize", question_id: currentQuestion.current ?? undefined });
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("paste", onPaste);
    window.addEventListener("resize", onResize);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("paste", onPaste);
      window.removeEventListener("resize", onResize);
    };
  }, [active]);

  return useCallback(() => {
    if (queue.current.length === 0) return;
    const batch = queue.current.splice(0, 100);
    publicQuiz.events(token, batch).catch(() => {
      // telemetry is best-effort; never block the quiz on it
    });
  }, [token]);
}

export default function QuizPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [phase, setPhase] = useState<Phase>("loading");
  const [state, setState] = useState<QuizState | null>(null);
  const [question, setQuestion] = useState<QuizQuestion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const advancedFor = useRef<string | null>(null);

  const remaining = useCountdown(question?.deadline_at ?? null);
  const flushTelemetry = useIntegrityTelemetry(
    token,
    phase === "question",
    question?.id ?? null,
  );

  const fail = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 404) setPhase("invalid");
    else if (err instanceof ApiError && err.status === 410) setPhase("expired");
    else setError(err instanceof Error ? err.message : "Something went wrong");
  }, []);

  useEffect(() => {
    publicQuiz
      .state(token)
      .then((s) => {
        setState(s);
        if (s.status === "completed") setPhase("done");
        else if (s.status === "expired") setPhase("expired");
        else setPhase("intro");
      })
      .catch(fail);
  }, [token, fail]);

  const advance = useCallback(() => {
    setBusy(true);
    publicQuiz
      .next(token)
      .then((next) => {
        if (next.done || next.question === null) {
          setQuestion(null);
          setPhase("done");
        } else {
          setQuestion(next.question);
          setPhase("question");
        }
      })
      .catch(fail)
      .finally(() => setBusy(false));
  }, [token, fail]);

  // deadline hit with no answer → let the server resolve it and move on
  useEffect(() => {
    if (
      phase === "question" &&
      question !== null &&
      remaining !== null &&
      remaining === 0 &&
      advancedFor.current !== question.id
    ) {
      advancedFor.current = question.id;
      advance();
    }
  }, [phase, question, remaining, advance]);

  async function answer(key: string) {
    if (question === null || busy) return;
    setBusy(true);
    setError(null);
    try {
      await publicQuiz.answer(token, question.id, key);
    } catch {
      // late or already-resolved answers are fine to ignore — just move on
    }
    flushTelemetry();
    advance();
  }

  const shell = "mx-auto max-w-2xl px-4 py-16";

  if (phase === "loading") {
    return <main className={shell}>Loading…</main>;
  }
  if (phase === "invalid") {
    return (
      <main className={shell}>
        <h1 className="text-xl font-semibold">This quiz link is not valid</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Double-check the link from your application confirmation.
        </p>
      </main>
    );
  }
  if (phase === "expired") {
    return (
      <main className={shell}>
        <h1 className="text-xl font-semibold">This quiz has expired</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Quizzes must be started within 24 hours of applying. Your application itself was
          received — the team can still review it.
        </p>
      </main>
    );
  }
  if (phase === "done") {
    return (
      <main className={shell}>
        <h1 className="text-xl font-semibold">Quiz completed — thank you!</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">
          Your answers were recorded alongside your application. The team will be in touch.
        </p>
      </main>
    );
  }
  if (phase === "intro" && state !== null) {
    return (
      <main className={shell}>
        <h1 className="text-xl font-semibold">Quick skills check</h1>
        <ul className="mt-4 list-disc space-y-1 pl-5 text-zinc-600 dark:text-zinc-400">
          <li>{state.total} multiple-choice questions, one at a time</li>
          <li>Each has a short time limit (about 15 seconds)</li>
          <li>Once a question is shown, the clock runs — you cannot go back</li>
          <li>You get a single attempt</li>
        </ul>
        <button
          type="button"
          onClick={advance}
          disabled={busy}
          className="mt-6 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {busy ? "…" : "Start the quiz"}
        </button>
        {error ? (
          <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
      </main>
    );
  }
  if (phase === "question" && question !== null) {
    return (
      <main className={shell}>
        <div className="flex items-center justify-between text-sm text-zinc-500">
          <span>
            Question {question.index} of {question.total}
          </span>
          <span
            aria-label="seconds remaining"
            className={remaining !== null && remaining <= 5 ? "font-semibold text-red-600" : ""}
          >
            {remaining ?? question.time_limit_seconds}s
          </span>
        </div>
        <div className="prose prose-zinc mt-4 dark:prose-invert">
          <ReactMarkdown>{question.prompt_md}</ReactMarkdown>
        </div>
        <div className="mt-6 space-y-2">
          {question.options.map((option) => (
            <button
              key={option.key}
              type="button"
              disabled={busy}
              onClick={() => answer(option.key)}
              className="block w-full rounded-lg border border-zinc-300 px-4 py-3 text-left text-sm hover:border-zinc-500 hover:bg-zinc-50 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              <ReactMarkdown>{option.text_md}</ReactMarkdown>
            </button>
          ))}
        </div>
        {error ? (
          <p role="alert" className="mt-3 text-sm text-red-600 dark:text-red-400">
            {error}
          </p>
        ) : null}
      </main>
    );
  }
  return null;
}
