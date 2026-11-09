/** Admin UI message catalog (board card "Admin UI multi-language").
 *
 * English is the source. Every other locale is typed as
 * `Record<MessageKey, string>`, so `pnpm typecheck` (CI) fails on a missing
 * or an unknown key; messages.test.ts also checks placeholders.
 * Placeholders are `{name}`, filled by `translate`.
 *
 * Coverage grows by surface: the admin shell and the Account language card
 * first. Candidate pages are out of scope (separate card). */

export const LOCALES = ["en", "de"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

/** Each language named in itself, for the picker. */
export const LOCALE_NAMES: Record<Locale, string> = { en: "English", de: "Deutsch" };

const en = {
  "nav.label": "Admin navigation",
  "nav.open": "Open navigation",
  "nav.close": "Close navigation",
  "nav.dashboard": "Dashboard",
  "nav.jobs": "Jobs",
  "nav.applicants": "Applicants",
  "nav.reports": "Reports",
  "nav.questions": "Questions",
  "nav.questionnaires": "Questionnaires",
  "nav.team": "Team",
  "nav.settings": "Settings",
  "nav.applicantsNew": "{count} new",
  "nav.applicantsNewTitle": "{count} new applicants",
  "nav.applicantsAria": "Applicants, {count} new applicants",
  "shell.signOut": "Sign out",
  "shell.backendDownTitle": "Can't reach the backend",
  "shell.backendDownBody":
    "The admin app couldn't load your session. The API may be restarting - check the backend container if this persists.",
  "shell.retry": "Retry",
  "language.title": "Language",
  "language.description": "Language of the admin app in this browser. Candidate pages are not affected.",
  "language.label": "Interface language",
  "language.partial": "German covers the navigation so far. Other screens stay in English until they are translated.",
} as const;

export type MessageKey = keyof typeof en;
export type Messages = Record<MessageKey, string>;

const de: Messages = {
  "nav.label": "Admin-Navigation",
  "nav.open": "Navigation öffnen",
  "nav.close": "Navigation schließen",
  "nav.dashboard": "Dashboard",
  "nav.jobs": "Stellen",
  "nav.applicants": "Bewerbungen",
  "nav.reports": "Berichte",
  "nav.questions": "Fragen",
  "nav.questionnaires": "Fragebögen",
  "nav.team": "Team",
  "nav.settings": "Einstellungen",
  "nav.applicantsNew": "{count} neu",
  "nav.applicantsNewTitle": "{count} neue Bewerbungen",
  "nav.applicantsAria": "Bewerbungen, {count} neue Bewerbungen",
  "shell.signOut": "Abmelden",
  "shell.backendDownTitle": "Backend nicht erreichbar",
  "shell.backendDownBody":
    "Die Admin-App konnte Ihre Sitzung nicht laden. Die API startet eventuell neu. Prüfen Sie den Backend-Container, falls das anhält.",
  "shell.retry": "Erneut versuchen",
  "language.title": "Sprache",
  "language.description":
    "Sprache der Admin-App in diesem Browser. Seiten für Bewerberinnen und Bewerber sind nicht betroffen.",
  "language.label": "Sprache der Oberfläche",
  "language.partial":
    "Auf Deutsch ist bisher die Navigation übersetzt. Andere Bereiche bleiben Englisch, bis sie übersetzt sind.",
};

export const MESSAGES: Record<Locale, Messages> = { en, de };

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

/** Look up `key` in `locale` (English as the fallback) and fill `{name}`
 * placeholders from `vars`. An unknown placeholder stays visible. */
export function translate(
  locale: Locale,
  key: MessageKey,
  vars?: Record<string, string | number>,
): string {
  const template = MESSAGES[locale]?.[key] ?? en[key];
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}
