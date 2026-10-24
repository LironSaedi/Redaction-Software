// Case-wide "redact additional text": turning the textarea into terms, with the same limits as the server.

import type { ExtraTerm } from "../types";

export const MAX_TERMS = 500;
export const MAX_TERM_LENGTH = 500;

export interface TermOptions {
  regex: boolean;
  case_sensitive: boolean;
  whole_word: boolean;
  entity: string;
}

export interface ParsedTerms {
  terms: ExtraTerm[];
  problems: string[];
}

/** One entry per line; blank lines and duplicates dropped; limits checked like the server does. */
export function parseTerms(text: string, o: TermOptions): ParsedTerms {
  const problems: string[] = [];
  const seen = new Set<string>();
  const terms: ExtraTerm[] = [];
  text.split(/\r?\n/).forEach((line, i) => {
    const t = line.trim();
    if (!t) return;
    if (t.length > MAX_TERM_LENGTH) {
      problems.push(`Line ${i + 1} is longer than ${MAX_TERM_LENGTH} characters.`);
      return;
    }
    if (o.regex) {
      try {
        if (new RegExp(t).test("")) problems.push(`Line ${i + 1}: the pattern matches empty text.`);
      } catch {
        // JavaScript and Python patterns differ slightly; the server has the final word
      }
    }
    const key = o.case_sensitive ? t : t.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    terms.push({ text: t, regex: o.regex, case_sensitive: o.case_sensitive, whole_word: o.whole_word, entity: o.entity });
  });
  if (!terms.length && !problems.length) problems.push("Enter at least one word, phrase, number or pattern.");
  if (terms.length > MAX_TERMS) problems.push(`At most ${MAX_TERMS} entries at a time (you have ${terms.length}).`);
  return { terms, problems };
}

/** Short description of an entry's options for the remembered list. */
export function termFlags(t: ExtraTerm): string[] {
  const out: string[] = [];
  if (t.regex) out.push("pattern");
  if (t.case_sensitive) out.push("match case");
  if (t.whole_word === false) out.push("partial words");
  return out;
}

export function sameTerm(a: ExtraTerm, b: ExtraTerm): boolean {
  return (
    a.text === b.text &&
    !!a.regex === !!b.regex &&
    !!a.case_sensitive === !!b.case_sensitive &&
    (a.whole_word ?? true) === (b.whole_word ?? true)
  );
}
