"use client";

import { useEffect, useState } from "react";

import { KeyRound } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import { apiKeys, type ApiKey, type ApiKeyCreated, type ApiKeyScope } from "@/lib/api";

/** Developers page card (card D4 part A): mint, list and revoke the
 * company's API keys. The secret is readable once, right after creation;
 * the list only ever shows the prefix. Revoked keys stay listed, struck
 * through, so the trail matches the activity log. */

const inputCls =
  "h-9 rounded-md border-[1.5px] border-edge bg-surface px-3 text-[13px] outline-none focus:border-accent";

function formatDate(value: string | null): string {
  if (value === null) return "never";
  return new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function ApiKeysCard() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [name, setName] = useState("");
  const [scope, setScope] = useState<ApiKeyScope>("read");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    apiKeys
      .list()
      .then(setKeys)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to load"));
  }

  useEffect(reload, []);

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const key = await apiKeys.create({ name: name.trim(), scope });
      setCreated(key);
      setName("");
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the key");
    } finally {
      setBusy(false);
    }
  }

  async function handleRevoke(id: string) {
    setError(null);
    try {
      await apiKeys.revoke(id);
      setConfirmId(null);
      if (created?.id === id) setCreated(null);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke the key");
    }
  }

  return (
    <div className="card p-4" data-testid="api-keys-card">
      <div className="flex items-center gap-2">
        <KeyRound aria-hidden className="h-4 w-4 text-g500" />
        <p className="text-[13.5px] font-semibold">API keys</p>
      </div>
      <p className="mt-1 text-[12.5px] leading-[18px] text-g500">
        Bearer tokens for your own tools: <span className="font-mono">read</span> lists
        applicants and exports, <span className="font-mono">write</span> can also move stages.
        The secret is shown once.
      </p>

      {created ? (
        <div
          role="status"
          className="mt-3 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2.5 text-[12.5px] text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200"
        >
          <p className="font-medium">
            {created.name} is ready. Copy it now, it won&apos;t be shown again.
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate font-mono text-[12px]">{created.secret}</code>
            <CopyButton text={created.secret} label="Copy API key" />
          </div>
        </div>
      ) : null}

      <form onSubmit={handleCreate} className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-g500">Key name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            maxLength={100}
            placeholder="Zapier"
            className={`${inputCls} w-44`}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-g500">Scope</span>
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value as ApiKeyScope)}
            className={inputCls}
          >
            <option value="read">read</option>
            <option value="write">write</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={busy || name.trim() === ""}
          className="inline-flex h-9 items-center rounded-md bg-inverse px-3 text-[13px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
        >
          Create key
        </button>
      </form>

      {error ? (
        <p role="alert" className="mt-2 text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}

      {keys === null ? (
        <div aria-busy="true" className="mt-3 h-8 animate-pulse rounded-md bg-muted-fill" />
      ) : keys.length === 0 ? (
        <p className="mt-3 text-[12.5px] text-g500">No keys yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-divider">
          {keys.map((key) => (
            <li key={key.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <span
                className={`text-[13px] font-medium ${key.revoked_at ? "text-g400 line-through" : ""}`}
              >
                {key.name}
              </span>
              <span className="font-mono text-[11.5px] text-g500">{key.prefix}</span>
              <span className="rounded-full bg-muted-fill px-2 py-0.5 font-mono text-[10.5px] text-g600">
                {key.scope}
              </span>
              <span className="ml-auto font-mono text-[11px] text-g400">
                {key.revoked_at
                  ? `revoked ${formatDate(key.revoked_at)}`
                  : `last used ${formatDate(key.last_used_at)}`}
              </span>
              {key.revoked_at ? null : confirmId === key.id ? (
                <span className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => void handleRevoke(key.id)}
                    className="inline-flex h-7 items-center rounded-md bg-red-600 px-2.5 text-[12px] font-semibold text-white hover:bg-red-700"
                  >
                    Revoke key
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmId(null)}
                    className="inline-flex h-7 items-center rounded-md border border-edge px-2.5 text-[12px] text-g700"
                  >
                    Keep
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  aria-label={`Revoke ${key.name}`}
                  onClick={() => setConfirmId(key.id)}
                  className="inline-flex h-7 items-center rounded-md border border-edge px-2.5 text-[12px] text-g700 hover:border-red-400 hover:text-red-600"
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
