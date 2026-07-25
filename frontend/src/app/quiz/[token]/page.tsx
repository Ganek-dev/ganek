"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { Check, Clock, Lock } from "lucide-react";

import { ApiError, publicQuiz, type QuizQuestion, type QuizState } from "@/lib/api";

/** Quiz exam surface (screens 05 / 26b): countdown ring above the stem,
 * A–D option cards, explicit lock step, keyboard controls. Layout is fixed
 * per question — integrity telemetry records resize, so nothing may shift
 * mid-question. Client timers are cosmetic; the server owns deadlines. */

const RED = "oklch(0.45 0.120 25)";

function useCountdownMs(deadline: string | null): number | null {
  // remaining time is derived at render from a ticking clock — no state
  // writes inside effects, and no bogus initial value racing the timer
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 200);
    return () => clearInterval(timer);
  }, []);
  if (!deadline) return null;
  return Math.max(0, new Date(deadline).getTime() - now);
}

function CountdownRing({
  remainingMs,
  limitSeconds,
}: {
  remainingMs: number;
  limitSeconds: number;
}) {
  const circumference = 283; // 2πr for r=45
  const total = limitSeconds * 1000;
  const fraction = total > 0 ? Math.min(1, Math.max(0, remainingMs / total)) : 0;
  const seconds = Math.max(0, Math.ceil(remainingMs / 1000));
  const urgent = seconds <= 5;
  const label = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  return (
    <div className="relative h-[84px] w-[84px] shrink-0 sm:h-[104px] sm:w-[104px]">
      <svg viewBox="0 0 104 104" className="h-full w-full -rotate-90">
        <circle cx="52" cy="52" r="45" fill="none" stroke="var(--divider)" strokeWidth="7" />
        <circle
          cx="52"
          cy="52"
          r="45"
          fill="none"
          stroke={urgent ? RED : "var(--brand-primary)"}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - fraction)}
          style={{ transition: "stroke-dashoffset 0.2s linear" }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span
          aria-label="time remaining"
          className="font-mono text-[19px] font-semibold tabular-nums sm:text-2xl"
          style={urgent ? { color: RED } : undefined}
        >
          {label}
        </span>
      </div>
    </div>
  );
}

/** Unwrap markdown paragraphs so stems/options stay inline (no layout jumps). */
const inlineMd = {
  p: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
};

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

const INTRO_RULES: [string, string][] = [
  ["1×", "a single attempt — once a question is shown, its clock runs"],
  ["0:00", "each question locks itself when its time is up"],
  ["→", "no going back between questions"],
];

export default function QuizPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;

  const [phase, setPhase] = useState<Phase>("loading");
  const [state, setState] = useState<QuizState | null>(null);
  const [question, setQuestion] = useState<QuizQuestion | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const advancedFor = useRef<string | null>(null);

  const remainingMs = useCountdownMs(question?.deadline_at ?? null);
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
    setSelected(null);
    publicQuiz
      .next(token)
      .then((next) => {
        if (next.done || next.question === null) {
          setQuestion(null);
          setPhase("done");
          // refresh the answered/total counters for the finished screen
          publicQuiz
            .state(token)
            .then(setState)
            .catch(() => {});
        } else {
          setQuestion(next.question);
          setPhase("question");
        }
      })
      .catch(fail)
      .finally(() => setBusy(false));
  }, [token, fail]);

  const lock = useCallback(
    async (key: string) => {
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
    },
    [question, busy, token, flushTelemetry, advance],
  );

  // deadline hit → lock whatever is selected (server grace decides), else
  // let the server resolve the miss and move on
  useEffect(() => {
    if (
      phase === "question" &&
      question !== null &&
      remainingMs !== null &&
      remainingMs === 0 &&
      advancedFor.current !== question.id
    ) {
      advancedFor.current = question.id;
      const submit = selected;
      const timer = setTimeout(() => {
        if (submit !== null) void lock(submit);
        else advance();
      }, 0);
      return () => clearTimeout(timer);
    }
  }, [phase, question, remainingMs, selected, lock, advance]);

  // keyboard: A–D (or beyond) selects, Enter locks
  useEffect(() => {
    if (phase !== "question" || question === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && /^(input|textarea|select)$/i.test(target.tagName)) return;
      const letterIndex = event.key.length === 1 ? event.key.toUpperCase().charCodeAt(0) - 65 : -1;
      if (letterIndex >= 0 && letterIndex < question.options.length) {
        setSelected(question.options[letterIndex].key);
      } else if (event.key === "Enter" && selected !== null && !busy) {
        void lock(selected);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phase, question, selected, busy, lock]);

  const centered = "mx-auto flex min-h-screen max-w-[560px] flex-col justify-center px-5 py-16";

  if (phase === "loading") {
    return (
      <main className={centered} aria-busy="true">
        <div className="mx-auto h-[84px] w-[84px] animate-pulse rounded-full bg-muted-fill sm:h-[104px] sm:w-[104px]" />
        <div className="mx-auto mt-6 h-4 w-48 animate-pulse rounded-sm bg-muted-fill" />
      </main>
    );
  }
  if (phase === "invalid") {
    return (
      <main className={centered}>
        <h1 className="font-heading text-[22px] font-semibold">This quiz link is not valid</h1>
        <p className="mt-2 text-[15px] leading-[23px] text-g600">
          Double-check the link from your application confirmation.
        </p>
      </main>
    );
  }
  if (phase === "expired") {
    // screen 27c (visuals; request-a-new-link flow lands with D5)
    return (
      <main className={centered}>
        <div className="text-center">
          <div
            className="mx-auto flex h-11 w-11 items-center justify-center rounded-full"
            style={{ background: "oklch(0.96 0.04 55)" }}
          >
            <Clock
              aria-hidden
              className="h-5 w-5"
              strokeWidth={2.5}
              style={{ color: "oklch(0.55 0.16 55)" }}
            />
          </div>
          <h1 className="mt-5 font-heading text-[25px] leading-[1.2] font-semibold">
            This assessment link expired
          </h1>
          <p className="mx-auto mt-2.5 max-w-[420px] text-[14.5px] leading-[22px] text-g600 [text-wrap:pretty]">
            Links are valid for 24 hours after applying, and this one ran out. Your
            application itself was received — the team can still review it.
          </p>
        </div>
      </main>
    );
  }
  if (phase === "done") {
    // screen 20 — no score shown, ever
    return (
      <main className="flex min-h-screen flex-col bg-surface text-foreground">
        <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-divider px-4 sm:h-[60px] sm:px-7">
          <span className="text-[13px] font-medium text-g500 sm:text-sm">
            Skills assessment
          </span>
          {state ? (
            <span className="font-mono text-xs text-g600 sm:text-[13px]">
              {state.answered} / {state.total}
            </span>
          ) : null}
        </header>
        <div className="flex flex-1 items-center justify-center">
          <div className="flex w-full max-w-[560px] flex-col items-center px-5 py-12">
            <div className="relative h-24 w-24">
              <svg viewBox="0 0 96 96" className="h-full w-full -rotate-90">
                <circle
                  cx="48"
                  cy="48"
                  r="41"
                  fill="none"
                  stroke="var(--brand-primary)"
                  strokeWidth="7"
                  strokeLinecap="round"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <Check aria-hidden className="h-[34px] w-[34px] text-brand" strokeWidth={2.5} />
              </div>
            </div>
            <h1 className="mt-6 text-center font-heading text-[24px] leading-[1.2] font-semibold tracking-[-0.005em] sm:text-[28px]">
              That&apos;s it — submitted
            </h1>
            <p className="mt-3 max-w-[420px] text-center text-[15px] leading-[23px] text-g600 [text-wrap:pretty]">
              Your answers went straight to the hiring team, alongside your application.
            </p>
            {state ? (
              <div className="mt-6 font-mono text-xs text-g600">
                {state.answered} of {state.total} answered
              </div>
            ) : null}
            <div className="mt-6 w-full rounded-lg border border-edge px-5 py-[18px]">
              <div className="overline text-g500">What happens next</div>
              <div className="mt-2.5 flex items-center gap-2.5 text-sm leading-[21px] text-g700">
                <span className="font-mono text-xs font-semibold text-brand">01</span>
                <span>The team reviews your application and assessment together</span>
              </div>
              <div className="mt-2 flex items-center gap-2.5 text-sm leading-[21px] text-g700">
                <span className="font-mono text-xs font-semibold text-brand">02</span>
                <span>You hear back by email, either way</span>
              </div>
            </div>
            <p className="mt-4 font-mono text-[11px] text-g400">You can close this tab now.</p>
          </div>
        </div>
      </main>
    );
  }
  if (phase === "intro" && state !== null) {
    return (
      <main className={centered}>
        <div className="overline text-g500">Skills assessment</div>
        <h1 className="mt-2 font-heading text-[27px] leading-[1.2] font-semibold tracking-[-0.01em]">
          Quick skills check
        </h1>
        <p className="mt-3 text-[15px] leading-[23px] text-g600">
          {state.total} multiple-choice question{state.total === 1 ? "" : "s"}, served one at
          a time with a short per-question timer.
        </p>
        <div className="mt-6 flex flex-col gap-2.5 text-sm leading-5 text-g700">
          {INTRO_RULES.map(([marker, rule]) => (
            <div key={marker} className="flex gap-2.5">
              <span className="w-[34px] shrink-0 font-mono text-xs font-semibold text-brand">
                {marker}
              </span>
              <span>{rule}</span>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={advance}
          disabled={busy}
          className="mt-8 flex h-[46px] w-full items-center justify-center rounded-md bg-brand text-[15px] font-semibold text-brand-foreground hover:brightness-[0.94] disabled:bg-muted-fill disabled:text-g500"
        >
          {busy ? "…" : "Start the quiz"}
        </button>
        <p className="mt-4 text-center font-mono text-[11px] text-g400">
          Find a quiet spot — tab switches are recorded
        </p>
        {error ? (
          <p role="alert" className="mt-3 text-sm" style={{ color: RED }}>
            {error}
          </p>
        ) : null}
      </main>
    );
  }
  if (phase === "question" && question !== null) {
    const ms = remainingMs ?? question.time_limit_seconds * 1000;
    const seconds = Math.ceil(ms / 1000);
    const missWarning = seconds <= 5 && selected === null;
    return (
      <main className="flex min-h-screen flex-col bg-surface text-foreground">
        <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-divider px-4 sm:h-[60px] sm:px-7">
          <span className="text-[13px] font-medium text-g500 sm:text-sm">
            Skills assessment
          </span>
          <span className="font-mono text-xs text-g600 sm:text-[13px]">
            Question {question.index} <span className="text-g400">of {question.total}</span>
          </span>
        </header>

        <div className="flex-1">
          <div className="mx-auto flex w-full max-w-[680px] flex-col items-center px-4 pt-6 pb-8 sm:px-6 sm:pt-9">
            <CountdownRing remainingMs={ms} limitSeconds={question.time_limit_seconds} />
            <div className="overline mt-3.5 text-[10.5px] text-g500 sm:mt-5 sm:text-[11.5px]">
              Single choice · {question.time_limit_seconds}s for this question
            </div>
            <h1 className="quiz-stem mt-2.5 text-center font-heading text-[19px] leading-[1.35] font-medium [text-wrap:pretty] sm:mt-3.5 sm:text-[25px] sm:tracking-[-0.005em]">
              <ReactMarkdown components={inlineMd}>{question.prompt_md}</ReactMarkdown>
            </h1>

            <div className="mt-[18px] flex w-full flex-col gap-2 sm:mt-7 sm:gap-2.5">
              {question.options.map((option, index) => {
                const letter = String.fromCharCode(65 + index);
                const isSelected = selected === option.key;
                return (
                  <button
                    key={option.key}
                    type="button"
                    disabled={busy}
                    aria-pressed={isSelected}
                    onClick={() => setSelected(option.key)}
                    className={
                      "flex min-h-11 w-full items-center gap-3 rounded-lg border-[1.5px] px-3.5 py-[13px] text-left sm:gap-3.5 sm:px-4 sm:py-3.5 " +
                      (isSelected ? "border-brand" : "border-edge hover:border-g400")
                    }
                    style={
                      isSelected
                        ? {
                            background:
                              "color-mix(in oklab, var(--brand-primary) 5%, var(--surface))",
                          }
                        : undefined
                    }
                  >
                    <span
                      className={
                        "flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] font-mono text-[11.5px] font-semibold sm:h-[26px] sm:w-[26px] sm:text-[12.5px] " +
                        (isSelected
                          ? "bg-brand text-brand-foreground"
                          : "border border-edge text-g500")
                      }
                    >
                      {letter}
                    </span>
                    <span
                      className={
                        "text-[14.5px] leading-[21px] sm:text-base sm:leading-6" +
                        (isSelected ? " font-medium" : "")
                      }
                    >
                      <ReactMarkdown components={inlineMd}>{option.text_md}</ReactMarkdown>
                    </span>
                  </button>
                );
              })}
            </div>

            {/* desktop lock row */}
            <div className="mt-6 hidden w-full items-center justify-between sm:flex">
              <span
                className="font-mono text-[11.5px]"
                style={missWarning ? { color: RED } : undefined}
              >
                <span className={missWarning ? "" : "text-g400"}>
                  {missWarning
                    ? "no answer selected — locks as missed at 0:00"
                    : "Locks automatically at 0:00"}
                </span>
              </span>
              <button
                type="button"
                disabled={busy || selected === null}
                onClick={() => selected !== null && void lock(selected)}
                className="inline-flex h-11 items-center gap-2 rounded-md bg-brand px-[22px] text-[15px] font-semibold text-brand-foreground hover:brightness-[0.94] disabled:bg-muted-fill disabled:text-g500 disabled:hover:brightness-100"
              >
                <Lock aria-hidden className="h-[15px] w-[15px]" />
                Lock answer
              </button>
            </div>

            {error ? (
              <p role="alert" className="mt-3 text-sm" style={{ color: RED }}>
                {error}
              </p>
            ) : null}
          </div>
        </div>

        {/* mobile bottom bar */}
        <div className="shrink-0 border-t border-divider px-4 pt-3.5 pb-[18px] sm:hidden">
          <button
            type="button"
            disabled={busy || selected === null}
            onClick={() => selected !== null && void lock(selected)}
            className="flex h-12 w-full items-center justify-center gap-2 rounded-md bg-brand text-[15px] font-semibold text-brand-foreground hover:brightness-[0.94] disabled:bg-muted-fill disabled:text-g500"
          >
            <Lock aria-hidden className="h-[15px] w-[15px]" />
            Lock answer
          </button>
          <p
            className="mt-2 text-center font-mono text-[10px]"
            style={missWarning ? { color: RED } : undefined}
          >
            <span className={missWarning ? "" : "text-g400"}>
              {missWarning
                ? "no answer selected — locks as missed at 0:00"
                : "one shot — locks automatically at 0:00"}
            </span>
          </p>
        </div>

        <footer className="hidden h-11 shrink-0 items-center justify-center gap-6 font-mono text-[11px] text-g400 sm:flex">
          <span>A–D to select · Enter to lock</span>
          <span>one shot — no going back</span>
          <span>tab switches are recorded</span>
        </footer>
      </main>
    );
  }
  return null;
}
