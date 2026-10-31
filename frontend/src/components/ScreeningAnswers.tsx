import { Check, CircleAlert } from "lucide-react";

import type { ScreeningAnswer } from "@/lib/api";

/** The applicant's answers to the job's screening questions, as asked (the
 * snapshot taken at apply time). A row that differs from the recruiter's
 * preferred answer is marked and names the preferred answer; a row that
 * matches gets a check. Information for the reader, never a verdict: no
 * stage moves on it (hard rule 5), and the tone stays neutral. */

function describe(answer: ScreeningAnswer): string {
  if (answer.type === "acknowledgment") return answer.answer === true ? "Accepted" : "Not accepted";
  if (answer.answer === null || answer.answer === "") return "Not answered";
  if (answer.type === "yes_no") return answer.answer === "yes" ? "Yes" : "No";
  return String(answer.answer);
}

function preferredLabel(answer: ScreeningAnswer): string {
  if (answer.preferred === null) return "";
  if (answer.type === "yes_no") return answer.preferred === "yes" ? "Yes" : "No";
  return answer.preferred;
}

export function ScreeningAnswers({ answers }: { answers: ScreeningAnswer[] }) {
  if (answers.length === 0) return null;
  return (
    <div className="mt-5">
      <p className="font-mono text-[11px] tracking-[0.08em] text-g500 uppercase">
        Screening answers
      </p>
      <ul className="mt-2 divide-y divide-divider rounded-md border border-edge">
        {answers.map((answer) => {
          const skipped = answer.answer === null || answer.answer === "";
          return (
            <li key={answer.question_id} className="flex items-start gap-3 px-3.5 py-2.5">
              <span className="mt-0.5 shrink-0" aria-hidden>
                {answer.match === false ? (
                  <CircleAlert className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                ) : answer.match === true ? (
                  <Check className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                ) : (
                  <span className="block h-4 w-4" />
                )}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] text-g500">{answer.prompt}</p>
                <p className={`text-sm ${skipped && answer.type !== "acknowledgment" ? "text-g500" : "text-foreground"}`}>
                  {describe(answer)}
                </p>
                {answer.match === false ? (
                  <p className="mt-0.5 text-[12.5px] text-amber-700 dark:text-amber-400">
                    <span className="font-medium">Mismatch</span>
                    {" · "}Preferred: {preferredLabel(answer)}
                  </p>
                ) : answer.match === true ? (
                  <p className="mt-0.5 text-[12.5px] text-g500">Matches the preferred answer</p>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
