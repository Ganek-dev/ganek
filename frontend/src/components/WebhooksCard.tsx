"use client";

import { useEffect, useState } from "react";

import { Webhook } from "lucide-react";

import { CopyButton } from "@/components/CopyButton";
import {
  webhooks,
  type WebhookEndpoint,
  type WebhookEndpointCreated,
  type DeliveryStatus,
  type WebhookEvent,
} from "@/lib/api";
import { richText, useLocale } from "@/lib/i18n/locale";
import { INTL_LOCALES, type MessageKey } from "@/lib/i18n/messages";

/** Developers page card (card D4 part B): register HTTPS endpoints for
 * application.created / stage.changed / quiz.completed, see the last
 * delivery per endpoint, send a realistic sample of the first subscribed
 * event, remove. The signing secret is readable once, right after
 * creation. */

const EVENTS: WebhookEvent[] = ["application.created", "stage.changed", "quiz.completed"];

const inputCls =
  "h-9 rounded-md border-[1.5px] border-edge bg-surface px-3 text-[13px] outline-none focus:border-accent";

const STATUS_LABEL: Record<DeliveryStatus, MessageKey> = {
  queued: "webhooks.statusQueued",
  delivered: "webhooks.statusDelivered",
  failed: "webhooks.statusFailed",
};

function formatWhen(value: string, intlLocale: string): string {
  return new Date(value).toLocaleString(intlLocale, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function LastDelivery({ delivery }: { delivery: WebhookEndpoint["last_delivery"] }) {
  const { locale, t } = useLocale();
  if (delivery === null) return <span className="text-g400">{t("webhooks.noDeliveries")}</span>;
  const tone =
    delivery.status === "delivered"
      ? "text-emerald-700 dark:text-emerald-300"
      : delivery.status === "failed"
        ? "text-red-600 dark:text-red-400"
        : "text-g500";
  return (
    <span className={tone}>
      {delivery.event} {t(STATUS_LABEL[delivery.status])}
      {delivery.last_error ? ` (${delivery.last_error})` : ""} ·{" "}
      {formatWhen(delivery.created_at, INTL_LOCALES[locale])}
    </span>
  );
}

export function WebhooksCard() {
  const { t } = useLocale();
  const [items, setItems] = useState<WebhookEndpoint[] | null>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<WebhookEvent[]>([...EVENTS]);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<WebhookEndpointCreated | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function reload() {
    webhooks
      .list()
      .then(setItems)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : t("webhooks.loadFailed")));
  }

  useEffect(reload, []);

  function toggle(event: WebhookEvent) {
    setEvents((current) =>
      current.includes(event) ? current.filter((e) => e !== event) : [...current, event],
    );
  }

  async function handleCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const hook = await webhooks.create({
        name: name.trim(),
        url: url.trim(),
        events: EVENTS.filter((e) => events.includes(e)),
      });
      setCreated(hook);
      setName("");
      setUrl("");
      setEvents([...EVENTS]);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("webhooks.addFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function handleTest(id: string) {
    setError(null);
    try {
      const delivery = await webhooks.test(id);
      setNotice(
        delivery.event === "ping"
          ? t("webhooks.testQueued")
          : t("webhooks.sampleQueued", { event: delivery.event }),
      );
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("webhooks.testFailed"));
    }
  }

  async function handleRemove(id: string) {
    setError(null);
    try {
      await webhooks.remove(id);
      setConfirmId(null);
      if (created?.id === id) setCreated(null);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("webhooks.removeFailed"));
    }
  }

  return (
    <div className="card p-4" data-testid="webhooks-card">
      <div className="flex items-center gap-2">
        <Webhook aria-hidden className="h-4 w-4 text-g500" />
        <p className="text-[13.5px] font-semibold">{t("webhooks.title")}</p>
      </div>
      <p className="mt-1 text-[12.5px] leading-[18px] text-g500">
        {richText(t("webhooks.description"), {
          header: <span className="font-mono">X-Ganek-Signature</span>,
        })}
      </p>

      {created ? (
        <div
          role="status"
          className="mt-3 rounded-md border border-emerald-300 bg-emerald-50 px-3 py-2.5 text-[12.5px] text-emerald-900 dark:border-emerald-500/40 dark:bg-emerald-500/10 dark:text-emerald-200"
        >
          <p className="font-medium">{t("webhooks.created", { name: created.name })}</p>
          <div className="mt-1.5 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate font-mono text-[12px]">{created.secret}</code>
            <CopyButton text={created.secret} label={t("webhooks.copySecret")} />
          </div>
        </div>
      ) : null}

      <form onSubmit={handleCreate} className="mt-3 flex flex-col gap-2">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] text-g500">{t("webhooks.name")}</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              maxLength={100}
              placeholder="Slack"
              className={`${inputCls} w-40`}
            />
          </label>
          <label className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="text-[12px] text-g500">{t("webhooks.url")}</span>
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              required
              type="url"
              placeholder="https://hooks.example.com/ganek"
              className={`${inputCls} w-full`}
            />
          </label>
        </div>
        <fieldset className="flex flex-wrap items-center gap-3">
          <legend className="sr-only">{t("webhooks.events")}</legend>
          {EVENTS.map((event) => (
            <label key={event} className="flex items-center gap-1.5 text-[12.5px] text-g700">
              <input
                type="checkbox"
                checked={events.includes(event)}
                onChange={() => toggle(event)}
                aria-label={event}
                className="h-3.5 w-3.5 accent-current"
              />
              <span className="font-mono">{event}</span>
            </label>
          ))}
          <button
            type="submit"
            disabled={busy || name.trim() === "" || url.trim() === "" || events.length === 0}
            className="ml-auto inline-flex h-9 items-center rounded-md bg-inverse px-3 text-[13px] font-semibold text-inverse-foreground hover:brightness-[0.94] disabled:opacity-50"
          >
            {t("webhooks.add")}
          </button>
        </fieldset>
      </form>

      {error ? (
        <p role="alert" className="mt-2 text-[12.5px] text-red-600 dark:text-red-400">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p role="status" className="mt-2 text-[12.5px] text-g600">
          {notice}
        </p>
      ) : null}

      {items === null ? (
        <div aria-busy="true" className="mt-3 h-8 animate-pulse rounded-md bg-muted-fill" />
      ) : items.length === 0 ? (
        <p className="mt-3 text-[12.5px] text-g500">{t("webhooks.empty")}</p>
      ) : (
        <ul className="mt-3 divide-y divide-divider">
          {items.map((hook) => (
            <li key={hook.id} className="flex flex-col gap-1 py-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="text-[13px] font-medium">{hook.name}</span>
                <span className="min-w-0 truncate font-mono text-[11.5px] text-g500">
                  {hook.url}
                </span>
                <span className="ml-auto flex items-center gap-1.5">
                  <button
                    type="button"
                    aria-label={t("webhooks.sendTestTo", { name: hook.name })}
                    onClick={() => void handleTest(hook.id)}
                    className="inline-flex h-7 items-center rounded-md border border-edge px-2.5 text-[12px] text-g700 hover:bg-muted-fill"
                  >
                    {t("webhooks.sendTest")}
                  </button>
                  {confirmId === hook.id ? (
                    <>
                      <button
                        type="button"
                        onClick={() => void handleRemove(hook.id)}
                        className="inline-flex h-7 items-center rounded-md bg-red-600 px-2.5 text-[12px] font-semibold text-white hover:bg-red-700"
                      >
                        {t("webhooks.removeConfirm")}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmId(null)}
                        className="inline-flex h-7 items-center rounded-md border border-edge px-2.5 text-[12px] text-g700"
                      >
                        {t("webhooks.keep")}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      aria-label={t("webhooks.removeName", { name: hook.name })}
                      onClick={() => setConfirmId(hook.id)}
                      className="inline-flex h-7 items-center rounded-md border border-edge px-2.5 text-[12px] text-g700 hover:border-red-400 hover:text-red-600"
                    >
                      {t("webhooks.remove")}
                    </button>
                  )}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px]">
                {hook.events.map((event) => (
                  <span key={event} className="rounded-full bg-muted-fill px-2 py-0.5 text-g600">
                    {event}
                  </span>
                ))}
                <LastDelivery delivery={hook.last_delivery} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
