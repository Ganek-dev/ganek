/** Admin UI message catalog (board card "Admin UI multi-language").
 *
 * English is the source. Every other locale is typed as
 * `Record<MessageKey, string>`, so `pnpm typecheck` (CI) fails on a missing
 * or an unknown key; messages.test.ts also checks placeholders.
 * Placeholders are `{name}`, filled by `translate`.
 *
 * Coverage grows by surface: the admin shell, the settings tabs, the
 * Account page's own cards and its sign-in methods and two-factor/sessions
 * cards so far. Candidate pages are out of scope (separate card). */

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
  "language.partial":
    "German covers the navigation, the settings tabs and the profile, password, sign-in methods, two-factor and sessions cards so far. Other screens stay in English until they are translated.",
  "settings.label": "Settings sections",
  "settings.branding": "Branding",
  "settings.hiring": "Hiring",
  "settings.privacy": "Privacy",
  "settings.emails": "Emails",
  "settings.team": "Team",
  "settings.account": "Account",
  "settings.developers": "Developers",
  "settings.billing": "Billing",
  "role.admin": "admin",
  "role.member": "member",
  "role.reviewer": "reviewer",
  "account.title": "Account",
  "account.profileTitle": "Profile",
  "account.profileDescription": "Shown to teammates on notes and activity.",
  "account.displayName": "Display name",
  "account.saveName": "Save name",
  "account.saved": "Saved",
  "account.email": "Email",
  "account.role": "Role",
  "account.roleAssigned": "{role} · assigned by workspace admin",
  "account.passwordTitle": "Password",
  "account.passwordAccess": "How you access this workspace.",
  "account.passwordSessions":
    "Changing your password signs out every other session; so does the button under Sessions below.",
  "account.passwordless":
    "You sign in with {via} - this account has no password. To add one, use Forgot password on the sign-in page.",
  "account.viaGoogle": "Google",
  "account.viaGoogleOr": "Google or {sso}",
  "account.viaSso": "single sign-on",
  "account.demoPassword":
    "Password changes are off on the demo workspace: the login is shared with every visitor.",
  "account.currentPassword": "Current password",
  "account.newPassword": "New password (min 10)",
  "account.confirmPassword": "Confirm new password",
  "account.passwordMismatch": "New passwords do not match.",
  "account.passwordFailed": "Failed to change password",
  "account.passwordChanged": "Password changed.",
  "account.updatePassword": "Update password",
  "account.later":
    "Email notification preferences and account deletion are planned for a later milestone.",
  "signIn.title": "Sign-in methods",
  "signIn.description": "Outside accounts that can sign you in. Signing in with one links it.",
  "signIn.sso": "Single sign-on",
  "signIn.linked": "Linked",
  "signIn.linkedOnly": "Linked · your only way to sign in",
  "signIn.notLinked": "Not linked · sign in with {method} once to link it",
  "signIn.unlink": "Unlink",
  "signIn.unlinkMethod": "Unlink {method}",
  "signIn.addPasswordFirst": "Add a password first (Forgot password on the sign-in page)",
  "signIn.confirm":
    "Unlink {method}? You can no longer sign in with it until you link it again by signing in with it.",
  "signIn.unlinkFailed": "Could not unlink {method}. Try again.",
  "common.cancel": "Cancel",
  "common.failed": "Something went wrong",
  "mfa.title": "Two-factor authentication",
  "mfa.on":
    "On. Every login asks for a code from your authenticator app; {count} recovery codes left.",
  "mfa.off": "Add a code from an authenticator app (any TOTP app) to every login.",
  "mfa.lockedTitle": "Off on the demo workspace",
  "mfa.turnOff": "Turn off",
  "mfa.setUp": "Set up",
  "mfa.locked":
    "Two-factor and session changes are off on the demo workspace: the login is shared with every visitor.",
  "mfa.fewCodes": "Few recovery codes left. Turn two-factor off and on again to get a fresh set.",
  "mfa.addKey": "Add this key to your authenticator app, then enter the code it shows.",
  "mfa.openApp": "Open in an authenticator app on this device",
  "mfa.code": "Code from the app",
  "mfa.turnOn": "Turn on",
  "mfa.enabled": "Two-factor authentication is on.",
  "mfa.saveCodes":
    "Save these recovery codes somewhere safe. Each one logs you in once if you lose the app. They are shown only now.",
  "mfa.savedCodes": "I saved them",
  "mfa.confirmPassword": "Confirm with your password",
  "mfa.confirmCode": "Confirm with a current code",
  "mfa.turnOffSubmit": "Turn off two-factor",
  "sessions.title": "Sessions",
  "sessions.done": "Done. Every other browser and device is signed out; this one stays.",
  "sessions.hint": "Lost a laptop or shared a login? Sign out everywhere except here.",
  "sessions.signOutEverywhere": "Sign out everywhere",
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
    "Auf Deutsch sind bisher die Navigation, die Einstellungs-Tabs sowie Profil, Passwort, Anmeldemethoden, Zwei-Faktor und Sitzungen übersetzt. Andere Bereiche bleiben Englisch, bis sie übersetzt sind.",
  "settings.label": "Einstellungsbereiche",
  "settings.branding": "Branding",
  "settings.hiring": "Recruiting",
  "settings.privacy": "Datenschutz",
  "settings.emails": "E-Mails",
  "settings.team": "Team",
  "settings.account": "Konto",
  "settings.developers": "Entwickler",
  "settings.billing": "Abrechnung",
  "role.admin": "Admin",
  "role.member": "Mitglied",
  "role.reviewer": "Prüfer",
  "account.title": "Konto",
  "account.profileTitle": "Profil",
  "account.profileDescription": "Wird Teammitgliedern bei Notizen und Aktivitäten angezeigt.",
  "account.displayName": "Anzeigename",
  "account.saveName": "Namen speichern",
  "account.saved": "Gespeichert",
  "account.email": "E-Mail",
  "account.role": "Rolle",
  "account.roleAssigned": "{role} · vom Workspace-Admin vergeben",
  "account.passwordTitle": "Passwort",
  "account.passwordAccess": "So melden Sie sich in diesem Workspace an.",
  "account.passwordSessions":
    "Eine Passwortänderung meldet alle anderen Sitzungen ab, ebenso die Schaltfläche im Bereich Sitzungen weiter unten.",
  "account.passwordless":
    "Sie melden sich mit {via} an. Dieses Konto hat kein Passwort. Um eines festzulegen, nutzen Sie auf der Anmeldeseite \"Forgot password\".",
  "account.viaGoogle": "Google",
  "account.viaGoogleOr": "Google oder {sso}",
  "account.viaSso": "Single Sign-on",
  "account.demoPassword":
    "Im Demo-Workspace sind Passwortänderungen deaktiviert: Die Anmeldung teilen sich alle Besucherinnen und Besucher.",
  "account.currentPassword": "Aktuelles Passwort",
  "account.newPassword": "Neues Passwort (mind. 10 Zeichen)",
  "account.confirmPassword": "Neues Passwort bestätigen",
  "account.passwordMismatch": "Die neuen Passwörter stimmen nicht überein.",
  "account.passwordFailed": "Passwort konnte nicht geändert werden",
  "account.passwordChanged": "Passwort geändert.",
  "account.updatePassword": "Passwort ändern",
  "account.later":
    "Einstellungen für E-Mail-Benachrichtigungen und das Löschen des Kontos sind für einen späteren Meilenstein geplant.",
  "signIn.title": "Anmeldemethoden",
  "signIn.description":
    "Externe Konten, mit denen Sie sich anmelden können. Eine Anmeldung damit verknüpft das Konto.",
  "signIn.sso": "Single Sign-on",
  "signIn.linked": "Verknüpft",
  "signIn.linkedOnly": "Verknüpft · Ihre einzige Anmeldemöglichkeit",
  "signIn.notLinked": "Nicht verknüpft · melden Sie sich einmal mit {method} an, um es zu verknüpfen",
  "signIn.unlink": "Trennen",
  "signIn.unlinkMethod": "{method} trennen",
  "signIn.addPasswordFirst":
    "Legen Sie zuerst ein Passwort fest (\"Forgot password\" auf der Anmeldeseite)",
  "signIn.confirm":
    "{method} trennen? Sie können sich damit erst wieder anmelden, wenn Sie es durch eine erneute Anmeldung verknüpfen.",
  "signIn.unlinkFailed": "{method} konnte nicht getrennt werden. Bitte erneut versuchen.",
  "common.cancel": "Abbrechen",
  "common.failed": "Etwas ist schiefgelaufen",
  "mfa.title": "Zwei-Faktor-Authentifizierung",
  "mfa.on":
    "Aktiv. Jede Anmeldung fragt nach einem Code aus Ihrer Authenticator-App; noch {count} Wiederherstellungscodes.",
  "mfa.off": "Fügen Sie jeder Anmeldung einen Code aus einer Authenticator-App (jede TOTP-App) hinzu.",
  "mfa.lockedTitle": "Im Demo-Workspace deaktiviert",
  "mfa.turnOff": "Deaktivieren",
  "mfa.setUp": "Einrichten",
  "mfa.locked":
    "Im Demo-Workspace sind Änderungen an Zwei-Faktor und Sitzungen deaktiviert: Die Anmeldung teilen sich alle Besucherinnen und Besucher.",
  "mfa.fewCodes":
    "Nur noch wenige Wiederherstellungscodes. Deaktivieren und aktivieren Sie Zwei-Faktor erneut, um neue zu erhalten.",
  "mfa.addKey":
    "Fügen Sie diesen Schlüssel Ihrer Authenticator-App hinzu und geben Sie dann den angezeigten Code ein.",
  "mfa.openApp": "In einer Authenticator-App auf diesem Gerät öffnen",
  "mfa.code": "Code aus der App",
  "mfa.turnOn": "Aktivieren",
  "mfa.enabled": "Zwei-Faktor-Authentifizierung ist aktiv.",
  "mfa.saveCodes":
    "Bewahren Sie diese Wiederherstellungscodes sicher auf. Jeder Code ermöglicht eine Anmeldung, falls Sie die App verlieren. Sie werden nur jetzt angezeigt.",
  "mfa.savedCodes": "Ich habe sie gespeichert",
  "mfa.confirmPassword": "Mit Ihrem Passwort bestätigen",
  "mfa.confirmCode": "Mit einem aktuellen Code bestätigen",
  "mfa.turnOffSubmit": "Zwei-Faktor deaktivieren",
  "sessions.title": "Sitzungen",
  "sessions.done": "Erledigt. Alle anderen Browser und Geräte sind abgemeldet, dieser bleibt angemeldet.",
  "sessions.hint": "Laptop verloren oder Anmeldung geteilt? Überall außer hier abmelden.",
  "sessions.signOutEverywhere": "Überall abmelden",
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
