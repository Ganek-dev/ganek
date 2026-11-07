import { describe, expect, it } from "vitest";

import {
  buildRows,
  detectDelimiter,
  guessMapping,
  mappingComplete,
  parseCsv,
} from "./csv-import";

describe("parseCsv", () => {
  it("handles quotes, doubled quotes, newlines in quotes, CRLF and a BOM", () => {
    const table = parseCsv(
      '﻿name,email,note\r\n"Doe, Jane",jane@x.dev,"said ""hi""\nthen left"\r\n\r\nBob,bob@x.dev,\r\n',
    );
    expect(table.headers).toEqual(["name", "email", "note"]);
    expect(table.rows).toEqual([
      ["Doe, Jane", "jane@x.dev", 'said "hi"\nthen left'],
      ["Bob", "bob@x.dev", ""],
    ]);
  });

  it("detects semicolon and tab files", () => {
    expect(detectDelimiter("Vorname;Nachname;E-Mail\n")).toBe(";");
    expect(detectDelimiter("name\temail\n")).toBe("\t");
    expect(detectDelimiter('"a;b",c\n')).toBe(",");
    expect(
      parseCsv("Vorname;Nachname;E-Mail\nAnna;Schmidt;anna@x.de").rows,
    ).toEqual([["Anna", "Schmidt", "anna@x.de"]]);
  });

  it("keeps a last line without a newline", () => {
    expect(parseCsv("name,email\nAda,ada@x.dev").rows).toEqual([
      ["Ada", "ada@x.dev"],
    ]);
  });
});

describe("guessMapping", () => {
  it("maps the Ganek export fully, preferring the full-name column", () => {
    const headers = [
      "candidate_name",
      "first_name",
      "last_name",
      "candidate_email",
      "job",
      "stage",
      "source",
    ];
    expect(guessMapping(headers)).toEqual({
      name: 0,
      first: null,
      last: null,
      email: 3,
      source: 6,
    });
  });

  it("maps first and last name columns (Greenhouse, Personio shapes)", () => {
    const mapping = guessMapping(["First Name", "Last Name", "Email Address"]);
    expect(mapping).toEqual({
      name: null,
      first: 0,
      last: 1,
      email: 2,
      source: null,
    });
    expect(mappingComplete(mapping)).toBe(true);
  });

  it("is incomplete without an email column", () => {
    expect(mappingComplete(guessMapping(["Name", "Phone"]))).toBe(false);
  });
});

describe("buildRows", () => {
  it("joins first and last, trims cells and leaves blanks for the server", () => {
    const table = parseCsv(
      "First,Last,Email,Source\n Ada , Lovelace ,ada@x.dev,linkedin\n,,bad,\n",
    );
    const rows = buildRows(table, guessMapping(table.headers));
    expect(rows).toEqual([
      { name: "Ada Lovelace", email: "ada@x.dev", source: "linkedin" },
      { name: "", email: "bad", source: null },
    ]);
  });
});
