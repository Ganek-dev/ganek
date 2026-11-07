/** CSV import of candidates (job overview): parse the file in the browser,
 * guess the column mapping, and turn the mapped rows into what
 * `POST /jobs/{id}/import` takes. The server validates and dedupes; this
 * only shapes the file. */

import type { CandidateImportRow } from "@/lib/api";

export const MAX_IMPORT_ROWS = 1000;

export interface CsvTable {
  headers: string[];
  rows: string[][];
}

/** The delimiter of the header line: comma, semicolon (Excel in most of
 * Europe) or tab, whichever appears most outside quotes. */
export function detectDelimiter(text: string): string {
  const firstLine = text.split(/\r?\n/, 1)[0] ?? "";
  let best = ",";
  let bestCount = 0;
  for (const candidate of [",", ";", "\t"]) {
    let count = 0;
    let quoted = false;
    for (const char of firstLine) {
      if (char === '"') quoted = !quoted;
      else if (!quoted && char === candidate) count += 1;
    }
    if (count > bestCount) {
      best = candidate;
      bestCount = count;
    }
  }
  return best;
}

/** RFC 4180 parsing: quoted fields, doubled quotes, newlines inside quotes,
 * CRLF or LF, a leading BOM. Blank lines are dropped. */
export function parseCsv(input: string): CsvTable {
  const text = input.replace(/^﻿/, "");
  const delimiter = detectDelimiter(text);
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === delimiter) {
      record.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      record.push(field);
      records.push(record);
      record = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field !== "" || record.length > 0) {
    record.push(field);
    records.push(record);
  }
  const nonBlank = records.filter((r) => r.some((cell) => cell.trim() !== ""));
  const [headers = [], ...rows] = nonBlank;
  return { headers: headers.map((h) => h.trim()), rows };
}

export interface ColumnMapping {
  /** one full-name column, or first + last */
  name: number | null;
  first: number | null;
  last: number | null;
  email: number | null;
  source: number | null;
}

const GUESSES: Record<keyof ColumnMapping, string[]> = {
  name: ["candidatename", "name", "fullname", "candidate", "applicantname"],
  first: ["firstname", "first", "givenname", "vorname", "prenom"],
  last: ["lastname", "last", "surname", "familyname", "nachname", "nom"],
  email: ["candidateemail", "email", "emailaddress", "mail", "applicantemail"],
  source: ["source", "candidatesource", "origin", "quelle"],
};

function key(header: string): string {
  return header.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** The mapping a header row suggests (the Ganek export maps fully). */
export function guessMapping(headers: string[]): ColumnMapping {
  const keys = headers.map(key);
  const find = (names: string[]) => {
    for (const name of names) {
      const index = keys.indexOf(name);
      if (index !== -1) return index;
    }
    return null;
  };
  const name = find(GUESSES.name);
  return {
    name,
    first: name === null ? find(GUESSES.first) : null,
    last: name === null ? find(GUESSES.last) : null,
    email: find(GUESSES.email),
    source: find(GUESSES.source),
  };
}

export function mappingComplete(mapping: ColumnMapping): boolean {
  return (
    mapping.email !== null && (mapping.name !== null || mapping.first !== null)
  );
}

function cell(row: string[], index: number | null): string {
  return index === null ? "" : (row[index] ?? "").trim();
}

/** The rows the API takes; a blank cell stays blank (the server counts the
 * row as invalid and reports its number). */
export function buildRows(
  table: CsvTable,
  mapping: ColumnMapping,
): CandidateImportRow[] {
  return table.rows.map((row) => {
    const name =
      mapping.name !== null
        ? cell(row, mapping.name)
        : `${cell(row, mapping.first)} ${cell(row, mapping.last)}`.trim();
    const source = cell(row, mapping.source);
    return { name, email: cell(row, mapping.email), source: source || null };
  });
}
