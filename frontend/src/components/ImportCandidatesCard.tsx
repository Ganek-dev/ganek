"use client";

import { useState } from "react";

import { api, type CandidateImportOut, type JobOut } from "@/lib/api";
import {
  MAX_IMPORT_ROWS,
  buildRows,
  guessMapping,
  mappingComplete,
  parseCsv,
  type ColumnMapping,
  type CsvTable,
} from "@/lib/csv-import";

/** CSV import on the job overview: people already in an ATS or a sheet get
 * an application without a CV and the job's invite. The file is parsed
 * here, the columns mapped, "Check file" asks the server for the counts
 * (dry run: new, already in this workspace or repeated, unusable), and only
 * then "Import" writes and mails. The origin is required: the first email
 * names it (GDPR art. 14, the person never applied themselves). */

const inputCls =
  "h-9 w-full rounded-md border-[1.5px] border-edge bg-surface px-3 text-[13px] outline-none focus:border-accent";
const buttonCls =
  "inline-flex h-8 items-center rounded-md bg-inverse px-3 text-[13px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50";
const PREVIEW_ROWS = 5;

const FIELDS: { key: keyof ColumnMapping; label: string }[] = [
  { key: "name", label: "Full name" },
  { key: "first", label: "First name" },
  { key: "last", label: "Last name" },
  { key: "email", label: "Email" },
  { key: "source", label: "Source (optional)" },
];

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function rowList(rows: number[]): string {
  const shown = rows.slice(0, 8).join(", ");
  return rows.length > 8 ? `${shown} and ${rows.length - 8} more` : shown;
}

export function ImportCandidatesCard({
  job,
  onImported,
}: {
  job: JobOut;
  onImported: () => void;
}) {
  const live = job.status === "published";
  const [fileName, setFileName] = useState<string | null>(null);
  const [table, setTable] = useState<CsvTable | null>(null);
  const [mapping, setMapping] = useState<ColumnMapping | null>(null);
  const [origin, setOrigin] = useState("");
  const [check, setCheck] = useState<CandidateImportOut | null>(null);
  const [done, setDone] = useState<CandidateImportOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setCheck(null);
    setError(null);
  }

  async function handleFile(file: File | undefined) {
    reset();
    setDone(null);
    setTable(null);
    setMapping(null);
    setFileName(file?.name ?? null);
    if (!file) return;
    const parsed = parseCsv(await file.text());
    if (parsed.rows.length === 0) {
      setError("The file has no rows below the header.");
      return;
    }
    if (parsed.rows.length > MAX_IMPORT_ROWS) {
      setError(`At most ${MAX_IMPORT_ROWS} rows per import - split the file.`);
      return;
    }
    setTable(parsed);
    setMapping(guessMapping(parsed.headers));
  }

  function setColumn(key: keyof ColumnMapping, value: string) {
    if (!mapping) return;
    reset();
    const index = value === "" ? null : Number(value);
    const next = { ...mapping, [key]: index };
    // a full-name column and first/last are alternatives
    if (key === "name" && index !== null)
      Object.assign(next, { first: null, last: null });
    if ((key === "first" || key === "last") && index !== null) next.name = null;
    setMapping(next);
  }

  async function submit(dryRun: boolean) {
    if (!table || !mapping) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.jobs.importCandidates(job.id, {
        rows: buildRows(table, mapping),
        origin: origin.trim(),
        dry_run: dryRun,
      });
      if (dryRun) {
        setCheck(result);
      } else {
        setDone(result);
        setCheck(null);
        setTable(null);
        setMapping(null);
        setFileName(null);
        setOrigin("");
        onImported();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed");
    } finally {
      setBusy(false);
    }
  }

  const ready = table !== null && mapping !== null && mappingComplete(mapping);
  const preview = ready ? buildRows(table, mapping).slice(0, PREVIEW_ROWS) : [];

  return (
    <div className="card px-5 py-[18px]">
      <span className="font-heading text-[15px] font-semibold">
        Import candidates
      </span>
      <p className="mt-1 text-[12.5px] text-g500">
        Screen people who are already in your ATS or a spreadsheet: upload a CSV
        with a name and an email per row. Each new person gets this job&apos;s
        invite, without a CV.
      </p>

      {!live ? (
        <p className="mt-3 text-[12.5px] text-g500">
          Publish the job to import candidates.
        </p>
      ) : (
        <>
          <label className="mt-3 block">
            <span className="sr-only">CSV file</span>
            <input
              type="file"
              accept=".csv,text/csv"
              aria-label="CSV file"
              disabled={busy}
              onChange={(event) => void handleFile(event.target.files?.[0])}
              className="block w-full text-[12.5px] text-g700 file:mr-3 file:h-8 file:rounded-md file:border file:border-edge file:bg-surface file:px-3 file:text-[12.5px] file:font-medium"
            />
          </label>

          {table && mapping ? (
            <div className="mt-3 space-y-3">
              <p className="font-mono text-[11.5px] text-g500">
                {fileName} · {plural(table.rows.length, "row")}
              </p>
              <div className="grid grid-cols-2 gap-2">
                {FIELDS.map(({ key, label }) => (
                  <label key={key} className="flex flex-col gap-1">
                    <span className="text-[12px] text-g500">{label}</span>
                    <select
                      aria-label={label}
                      value={mapping[key] ?? ""}
                      disabled={busy}
                      onChange={(event) => setColumn(key, event.target.value)}
                      className={inputCls}
                    >
                      <option value="">-</option>
                      {table.headers.map((header, index) => (
                        <option key={index} value={index}>
                          {header || `Column ${index + 1}`}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              {!mappingComplete(mapping) ? (
                <p className="text-[12.5px] text-g500">
                  Pick the email column and a full name or first name column.
                </p>
              ) : null}

              <label className="flex flex-col gap-1">
                <span className="text-[12px] text-g500">
                  Where did these people come from?
                </span>
                <input
                  value={origin}
                  maxLength={200}
                  disabled={busy}
                  placeholder="our Personio account"
                  onChange={(event) => {
                    reset();
                    setOrigin(event.target.value);
                  }}
                  className={inputCls}
                />
                <span className="text-[11.5px] text-g500">
                  Named in their first email: they never applied here
                  themselves, so the law asks you to say where their details
                  came from.
                </span>
              </label>

              {preview.length > 0 ? (
                <table className="w-full text-left text-[12px]">
                  <caption className="sr-only">
                    First rows as they will import
                  </caption>
                  <thead className="text-g500">
                    <tr>
                      <th className="py-1 font-medium">Name</th>
                      <th className="py-1 font-medium">Email</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((row, index) => (
                      <tr key={index} className="border-t border-divider">
                        <td className="max-w-[9rem] truncate py-1 pr-2">
                          {row.name || "-"}
                        </td>
                        <td className="max-w-[11rem] truncate py-1">
                          {row.email || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : null}

              {check ? (
                <div
                  role="status"
                  className="rounded-md border border-edge px-3 py-2.5 text-[12.5px]"
                >
                  <p>
                    <b className="font-semibold">
                      {plural(check.imported, "new candidate")}
                    </b>{" "}
                    will get the invite.
                  </p>
                  {check.duplicates > 0 ? (
                    <p className="mt-1 text-g500">
                      {plural(check.duplicates, "row")} skipped: already in this
                      workspace or repeated (rows{" "}
                      {rowList(check.duplicate_rows)}).
                    </p>
                  ) : null}
                  {check.invalid > 0 ? (
                    <p className="mt-1 text-g500">
                      {plural(check.invalid, "row")} skipped: no name or no
                      valid email (rows {rowList(check.invalid_rows)}).
                    </p>
                  ) : null}
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2">
                {check ? (
                  <button
                    type="button"
                    disabled={busy || check.imported === 0}
                    onClick={() => void submit(false)}
                    className={buttonCls}
                  >
                    Import {plural(check.imported, "candidate")} and send
                    invites
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={busy || !ready || origin.trim().length < 2}
                    onClick={() => void submit(true)}
                    className={buttonCls}
                  >
                    Check file
                  </button>
                )}
              </div>
            </div>
          ) : null}

          {done ? (
            <p
              role="status"
              className="mt-3 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2.5 text-[12.5px] text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200"
            >
              Imported {plural(done.imported, "candidate")}
              {done.duplicates + done.invalid > 0
                ? `, skipped ${done.duplicates + done.invalid}`
                : ""}
              . Invites are on their way.
            </p>
          ) : null}
        </>
      )}

      {error ? (
        <p
          role="alert"
          className="mt-2 text-[12.5px] text-red-600 dark:text-red-400"
        >
          {error}
        </p>
      ) : null}
    </div>
  );
}
